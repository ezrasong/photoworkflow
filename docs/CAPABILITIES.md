# Photo capability coverage

This inventory describes implementation coverage, not hardware/Adobe acceptance.
Advanced panels use the same packaged Python and persistent workspace.

| Existing capability | Desktop entry | Backend owner |
| --- | --- | --- |
| Natural-language file/folder editing and follow-ups | Conversation, saved sessions, picker/drop | prompt_chat, unified_batch, native_batch, OMP RPC |
| Local visual inspection | Conversation | vision, chat |
| Tone, warmth, tint, contrast, shadows/highlights, saturation | Photo controls; advanced recipe; precision editor | edits, pipeline |
| SCUNet / DRUNet, sigma, masked denoise | Controls; recipe; precision editor | edits |
| Mild out-of-focus correction, radius/strength, regional mask | Correct soft focus; conversation; recipe | focus, edits |
| MambaIRv2 / Real-ESRGAN 2×/4×, detail blend | Natural upscale; conversation | mambair, models |
| Face restoration single/batch/watch, bit depth, subject map | Controls; precision editor for 8-bit opt-in and mapping | harness, pipeline |
| Paint/import/erase masks; clone donor | Precision editor & masks | edit_panel |
| COCO selection/background complement, selective grade | Conversation; advanced recipe | selection, edits |
| Big-LaMa removal, selected GFPGAN faces, opt-in enforcement | Explicit conversation/manual recipe | unified_batch, selection, inpainting |
| Lightroom native Develop, curves, crop, lens, denoise | Conversation; advanced native batch | lightroom plug-in, native_batch |
| Photoshop local curves/clone, layered TIFF/PSD/PSB | Conversation; Results export | photoshop_local, photoshop |
| Before/after split, Fit/100%, pan, navigation, What changed | Embedded Results tab; native review retained for advanced workflows | photo-review, imaging, review_panel |
| Automatic local prompt correction, original/corrected history | Composer and Prompt Master tab | prompt_master, chat authorization boundary |
| Photo-based prompt suggestions; editable drafts before submission | Suggest prompts from photo; Prompt Master tab | prompt_master, vision |
| Public website reference browsing | Embedded Browser tab | Isolated Electron WebContentsView |
| HEIC/HEIF SDR preparation; RAW/DNG | Assistant selection | heif, native_batch |
| Local references and selected vault notes | Composer context buttons | references, vault, chat |
| Explicit Commons search with attribution | Search references opens local chooser; query sent only on Search | reference_browser, public_references |
| Chosen reference images, source links, licenses and hashes in Obsidian | Save chosen references in Photo Vault in chooser | vault, reference_browser |
| Person mapping, notes, Photo Vault, optional Obsidian | Precision tools & vault; Setup | vault |
| Recipe load/recompute, legacy text-only assistant | Precision editor | edit_panel, agent |
| Cancellation, atomic outputs, original/Adobe preservation | Stop safely; safe close; workers | runtime, pipeline, Adobe guards |
| All models, runtimes, Oh My Pi, Obsidian and vault; per-component repair | Setup → Install / repair complete setup | installation |

Native panels intentionally preserve precision behavior. Visual consolidation
into Solid can follow later. No video controls are presented.

Limits retained: SDR sRGB derivatives; HDR/unknown-color HEIF can be rejected;
RAW requires Lightroom; dimension/model limits and Adobe vendor failures remain.
There is no automatic CPU fallback. The shipped Mamba kernel supports compute
capability 12.0 only. RTX 5090 32 GB is the previously validated assistant hardware;
GPU detection is not a claim of sufficient VRAM on smaller devices.
