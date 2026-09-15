import React, { useEffect, useState } from "react";
import { ArrowUp } from "lucide-react";

/**
 * Appears once you are a screen down and returns you to the top. The landing
 * page runs several viewport-heights of pinned scroll, so getting back up
 * otherwise means a long drag.
 */
export default function BackToTop() {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      setShown(window.scrollY > window.innerHeight * 0.9);
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <button
      type="button"
      className={`back-to-top ${shown ? "is-shown" : ""}`}
      aria-label="Back to top"
      title="Back to top"
      tabIndex={shown ? 0 : -1}
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
    >
      <ArrowUp size={17} />
    </button>
  );
}
