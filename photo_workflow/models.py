import json
import sys
import time

from .runtime import ROOT, sha256, check_cancel

class Models:
    def __init__(self, restoration=True):
        import torch
        import torchvision.transforms.functional as functional
        # BasicSR 1.4.2 imports a torchvision module removed in torchvision 0.17.
        # Alias the maintained, equivalent public API without modifying site-packages.
        sys.modules.setdefault('torchvision.transforms.functional_tensor', functional)
        from gfpgan.archs.gfpganv1_clean_arch import GFPGANv1Clean
        from facexlib.utils.face_restoration_helper import FaceRestoreHelper

        if not torch.cuda.is_available():
            raise RuntimeError('CUDA GPU unavailable. Check driver; this workflow requires NVIDIA CUDA.')
        self.torch = torch
        self.manifest = json.loads((ROOT / 'models/manifest.json').read_text())
        for name, entry in self.manifest.items():
            if sha256(ROOT / 'models' / name) != entry['sha256']:
                raise RuntimeError('Model checksum mismatch: ' + name)
        self.device = torch.device('cuda')
        self.up = None
        self.helper = None
        self.face = None
        if not restoration:
            return
        self.face = GFPGANv1Clean(out_size=512, num_style_feat=512, channel_multiplier=2,
            decoder_load_path=None, fix_decoder=False, num_mlp=8, input_is_latent=True,
            different_w=True, narrow=1, sft_half=True)
        weights = torch.load(ROOT / 'models/GFPGANv1.4.pth', map_location='cpu', weights_only=True)
        self.face.load_state_dict(weights['params_ema'], strict=True)
        self.face.eval().to(self.device)
        self.helper = FaceRestoreHelper(1, face_size=512, crop_ratio=(1, 1),
            det_model='retinaface_resnet50', use_parse=True, device=self.device,
            model_rootpath=str(ROOT / 'models'))

    def upscale(self, rgb, scale):
        import cv2
        import numpy as np
        if self.up is None:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
            self.up = RealESRGANer(scale=4, model_path=str(ROOT / 'models/RealESRGAN_x4plus.pth'),
                model=RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23,
                              num_grow_ch=32, scale=4), tile=256, tile_pad=10, pre_pad=0,
                half=False, device=self.device)
        # Upstream tile_process catches RuntimeError and can leave incomplete output.
        # Our subclass-free replacement propagates failures to the atomic job boundary.
        self.up.tile_process = self._tile_process
        maximum = np.iinfo(rgb.dtype).max
        # Normalize by declared dtype, not brightness (dark uint16 must stay dark).
        with self.torch.inference_mode():
            self.up.pre_process(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR).astype(np.float32) / maximum)
            self.up.tile_process()
            output = self.up.post_process().squeeze(0).float().clamp_(0, 1).cpu().numpy()
        output = output[[2, 1, 0]].transpose(1, 2, 0)
        if scale != 4:
            output = cv2.resize(output, (rgb.shape[1]*scale, rgb.shape[0]*scale), interpolation=cv2.INTER_LANCZOS4)
        return np.clip(np.rint(output * maximum), 0, maximum).astype(rgb.dtype)

    def _tile_process(self):
        import math
        up = self.up
        _, channels, height, width = up.img.shape
        up.output = up.img.new_zeros((1, channels, height * 4, width * 4))
        for y in range(math.ceil(height / up.tile_size)):
            for x in range(math.ceil(width / up.tile_size)):
                check_cancel()
                x0, y0 = x * up.tile_size, y * up.tile_size
                x1, y1 = min(x0 + up.tile_size, width), min(y0 + up.tile_size, height)
                px0, py0 = max(x0 - up.tile_pad, 0), max(y0 - up.tile_pad, 0)
                px1, py1 = min(x1 + up.tile_pad, width), min(y1 + up.tile_pad, height)
                with self.torch.inference_mode():
                    tile = up.model(up.img[:, :, py0:py1, px0:px1])
                up.output[:, :, y0*4:y1*4, x0*4:x1*4] = tile[:, :,
                    (y0-py0)*4:(y1-py0)*4, (x0-px0)*4:(x1-px0)*4]

    def faces(self, rgb, scale, target=None):
        import cv2
        import numpy as np
        from basicsr.utils import img2tensor
        h = self.helper
        h.clean_all()
        maximum = np.iinfo(rgb.dtype).max
        detection = np.rint(rgb.astype(np.float32) / maximum * 255).astype(np.uint8)
        h.read_image(cv2.cvtColor(detection, cv2.COLOR_RGB2BGR))
        h.get_face_landmarks_5(only_center_face=False, eye_dist_threshold=5)
        indexes = list(range(len(h.all_landmarks_5)))
        if target is not None:
            from .selection import validate_target, choose_indices
            target = validate_target(target, face=True)
            indexes = choose_indices(h.det_faces, target['position'], rgb.shape[1])
            # Filter before alignment and GFPGAN: an unselected face never runs restoration.
            h.all_landmarks_5 = [h.all_landmarks_5[i] for i in indexes]
        self.face_selection = {'detected_boxes': [b.tolist() for b in h.det_faces],
                               'selected_indices': indexes, 'target': target}
        h.align_warp_face()
        width, height = rgb.shape[1] * scale, rgb.shape[0] * scale
        for matrix in h.affine_matrices:
            check_cancel()
            crop = cv2.warpAffine(rgb.astype(np.float32) / maximum, matrix, (512, 512),
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=(135/255,)*3)
            tensor = img2tensor(crop, bgr2rgb=False, float32=True)
            tensor = ((tensor - .5) / .5).unsqueeze(0).to(self.device)
            with self.torch.inference_mode():
                restored = self.face(tensor, return_rgb=False, weight=.5)[0]
                labels = h.face_parse(tensor)[0].argmax(dim=1).squeeze().cpu().numpy()
            face_float = restored.squeeze(0).float().clamp(-1, 1).add(1).div(2).permute(1, 2, 0).cpu().numpy()
            face = np.rint(face_float * maximum).astype(rgb.dtype)
            # Upstream semantic face classes exclude background, neck, hair and clothes.
            mask = np.isin(labels, list(range(1, 14)) + [15]).astype(np.float32)
            mask = cv2.GaussianBlur(mask, (101, 101), 11)
            mask = cv2.GaussianBlur(mask, (101, 101), 11)
            mask[:10] = mask[-10:] = 0
            mask[:, :10] = mask[:, -10:] = 0
            inverse = cv2.invertAffineTransform(matrix) * scale
            self.face_selection.setdefault('affine_matrices', []).append(matrix.tolist())
            layer = cv2.warpAffine(face, inverse, (width, height))
            mask = cv2.warpAffine(mask, inverse, (width, height))
            yield layer, np.clip(np.rint(mask * maximum), 0, maximum).astype(rgb.dtype), face

    def info(self):
        return {'torch': self.torch.__version__, 'cuda_runtime': self.torch.version.cuda,
                'gpu': self.torch.cuda.get_device_name(0), 'models': self.manifest}
