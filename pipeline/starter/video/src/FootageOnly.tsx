import { AbsoluteFill, OffthreadVideo, staticFile } from "remotion";

/**
 * public/footage.mp4 drawn exactly the way the main composition draws it (1080x1920, cover),
 * nothing else. Register it in Root.tsx with the same size, fps and duration as the main comp.
 * Matte source frames are rendered from THIS, not extracted with ffmpeg: Remotion and an ffmpeg
 * PNG export convert the footage's colour differently (~5 L* on skin), so a cutout made from
 * ffmpeg frames makes the face jump in tone every time the cutout switches on or off.
 * If the main comp punches in, draw the same transform here.
 */
export const FootageOnly: React.FC = () => (
  <AbsoluteFill style={{ background: "black" }}>
    <OffthreadVideo src={staticFile("footage.mp4")} muted style={{ width: 1080, height: 1920, objectFit: "cover" }} />
  </AbsoluteFill>
);
