/**
 * Applies to the Studio and the CLI only — the Node APIs (`npx remotion bundle`, renderMedia)
 * ignore this file.
 */
import { Config } from "@remotion/cli/config";
import { enableTailwind } from "@remotion/tailwind-v4";

// PNG frames: the default JPEG (quality 80) rings around captions and plates and bands the sky —
// invisible in QuickTime, but Instagram's own re-encode then blows it up. The master is the
// high-quality intermediate (crf 12, set in master.sh — a config-wide crf breaks the wav pass);
// scripts/deliver.sh makes the one lossy platform encode.
Config.setVideoImageFormat("png");
// The default writes full-range BT.601 (yuvj420p, pc) — Instagram and many phones read it as
// limited range and shift contrast and colour. BT.709 limited range is the delivery standard.
Config.setColorSpace("bt709");
Config.setOverwriteOutput(true);

// The OffthreadVideo frame cache defaults to a share of free memory, which over a few thousand
// frames of 4K footage grows until a worker tab is killed. Remotion then opens a replacement tab
// that never finishes its font load, and the render dies with a misleading
// `delayRender(...) timed out` — the fonts are fine, the tab was starved.
Config.setOffthreadVideoCacheSizeInBytes(512 * 1024 * 1024);
Config.setConcurrency(3);

// webpack, not rspack: the Tailwind webpack loader is a silent no-op under rspack and every Tailwind
// class drops out of the render.
Config.overrideWebpackConfig(enableTailwind);
