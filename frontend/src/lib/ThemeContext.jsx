import React, { createContext, useContext, useState, useEffect } from "react";
import { readPref, writePref } from "./storage.js";

const ThemeContext = createContext({
  theme: "dark",
  toggleTheme: () => {},
  setTheme: () => {},
});

export function ThemeProvider({ children }) {
  // The product is dark-only. Light mode was removed rather than patched:
  // hundreds of high-specificity overrides made it unreliable, and the
  // forensic surfaces were designed against the dark palette.
  useEffect(() => {
    const root = document.documentElement;
    const body = document.body;
    root.classList.add("dark");
    root.classList.remove("light");
    body?.classList.add("dark");
    body?.classList.remove("light");
    root.setAttribute("data-theme", "dark");
    root.classList.add("glass-mode-active");
    body?.classList.add("glass-mode-active");
    // Clear any light preference left in storage from an earlier visit.
    if (readPref("chakravyuh_theme") !== "dark") writePref("chakravyuh_theme", "dark");
  }, []);

  const noop = () => {};

  return (
    <ThemeContext.Provider
      value={{
        theme: "dark",
        toggleTheme: noop,
        setTheme: noop,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
