import { cancelRender, Composition, continueRender, delayRender, Still } from "remotion";
import "./index.css";
import { FONT } from "./brand";
import config from "../reels.config.json";
import { DURATION, MyComposition } from "./Composition";
import { FootageOnly } from "./FootageOnly";
import { Cover } from "./Cover";
import { PosterCover } from "./PosterCover";

// Hold the render until the brand fonts are actually rasterised. @fontsource only DECLARES the
// faces; the browser fetches them lazily on first use, so `document.fonts.ready` alone resolves
// while the fallback is still active — measureText then measures the wrong (narrower) face and
// captions overflow the frame. Force the loads first, with a Cyrillic sample so that subset is
// fetched too (a bare load() only fetches the face that matches an empty string).
const SAMPLE = "абв АБВ abc";
const fontsLoaded = delayRender("brand fonts");
// only the families the user has chosen — before the interview the demo runs on the system font
const wanted = [
  ...(config.fonts.text ? [500, 600, 700].map((w) => `${w} 64px "${FONT.text}"`) : []),
  ...(config.fonts.poster ? [`${FONT.posterWeight} 200px "${FONT.poster}"`] : []),
];
Promise.all(wanted.map((f) => document.fonts.load(f, SAMPLE)))
  .then((faces) => {
    // An empty match = the family named in reels.config.json is not declared in index.css.
    // Without this the video silently renders (and measures) in the system fallback.
    const missing = faces.findIndex((f) => f.length === 0);
    if (missing !== -1) {
      throw new Error(
        `Font in "${wanted[missing]}" from reels.config.json is not loaded — ` +
          "npm i @fontsource/<family> and @import its weight files in src/index.css",
      );
    }
    return document.fonts.ready;
  })
  .then(() => continueRender(fontsLoaded))
  .catch((err) => cancelRender(err));

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <MyComposition />
      {/* matte.py renders the cutout frames from this, so the skin tone matches the main comp */}
      <Composition id="FootageOnly" component={FootageOnly} durationInFrames={DURATION} fps={30} width={1080} height={1920} />
      <Still
        id="Cover"
        component={Cover}
        width={1080}
        height={1920}
        defaultProps={{
          lines: [{ text: "монтаж" }, { text: "одной командой", em: true, accent: true }, { text: "в claude code" }],
          img: "cover-cutout.png",
          bg: "cover-bg.jpg",
        }}
      />
      <Still
        id="PosterCover"
        component={PosterCover}
        width={1080}
        height={1920}
        defaultProps={{
          bg: "poster-bg.jpg",
          cutout: "poster-cutout.png",
          kicker: "демо",
          lines: [{ text: "монтаж" }, { text: "одной", accent: true }, { text: "командой" }],
          top: 150,
          cap: 250,
          zoom: 1.15,
        }}
      />
    </>
  );
};
