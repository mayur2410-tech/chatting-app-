import { useEffect } from "react";

/**
 * Keeps --app-height equal to the visible viewport so the composer stays above the
 * on-screen keyboard on iOS Safari (which does not resize dvh when the keyboard opens).
 */
export function useViewportHeight(): void {
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;

    const update = () => {
      document.documentElement.style.setProperty("--app-height", `${vv.height}px`);
      // iOS may scroll the layout viewport when focusing an input; pin it back.
      if (window.scrollY !== 0) window.scrollTo(0, 0);
    };

    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
      document.documentElement.style.removeProperty("--app-height");
    };
  }, []);
}
