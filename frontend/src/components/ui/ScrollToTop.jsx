import React, { useState, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronUp } from "lucide-react";

export default function ScrollToTop() {
  const [visible, setVisible] = useState(false);
  const location = useLocation();

  // Scroll to top automatically when route changes
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [location.pathname]);

  // Track window scroll
  useEffect(() => {
    const handleScroll = () => {
      if (window.scrollY > 220) {
        setVisible(true);
      } else {
        setVisible(false);
      }
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const scrollToTop = () => {
    window.scrollTo({
      top: 0,
      behavior: "smooth",
    });
  };

  return (
    <AnimatePresence>
      {visible && (
        <motion.button
          type="button"
          onClick={scrollToTop}
          initial={{ opacity: 0, y: 20, scale: 0.85 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 16, scale: 0.85 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          whileHover={{ scale: 1.08, y: -2 }}
          whileTap={{ scale: 0.94 }}
          aria-label="Scroll to top"
          title="Scroll to top"
          className="scroll-to-top-btn fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-full px-3.5 py-2.5 shadow-2xl backdrop-blur-md transition-all duration-200 cursor-pointer group"
        >
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[#d8b84d]/20 text-[#d8b84d] group-hover:bg-[#d8b84d] group-hover:text-black transition-colors">
            <ChevronUp size={16} strokeWidth={2.5} className="transition-transform group-hover:-translate-y-0.5" />
          </div>
          <span className="text-xs font-semibold tracking-wide hidden sm:inline-block pr-1">
            Top
          </span>
        </motion.button>
      )}
    </AnimatePresence>
  );
}
