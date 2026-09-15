import { BrowserRouter, HashRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { LandingPage } from "./components/LandingPage.jsx";
import AmbientRadar from "./components/AmbientRadar.jsx";
import AdminRoute from "./components/AdminRoute.jsx";
import RequireAuth from "./components/RequireAuth.jsx";
import DashboardPage from "./components/DashboardPage.jsx";
import { AuthPage } from "./components/AuthPage.jsx";
import ScrollToTop from "./components/ui/ScrollToTop.jsx";
import { ThemeProvider } from "./lib/ThemeContext.jsx";

const pageVariants = {
  initial: {
    opacity: 0,
    y: 16,
    scale: 0.992,
  },
  animate: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      duration: 0.38,
      ease: [0.16, 1, 0.3, 1],
    },
  },
  exit: {
    opacity: 0,
    y: -14,
    scale: 0.992,
    transition: {
      duration: 0.26,
      ease: [0.7, 0, 0.84, 0],
    },
  },
};

function AnimatedRoutes() {
  const location = useLocation();

  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route
          path="/"
          element={
            <motion.div variants={pageVariants} initial="initial" animate="animate" exit="exit" className="w-full">
              <LandingPage />
            </motion.div>
          }
        />
        <Route
          path="/dashboard"
          element={
            <motion.div variants={pageVariants} initial="initial" animate="animate" exit="exit" className="w-full">
              <RequireAuth>
                <DashboardPage />
              </RequireAuth>
            </motion.div>
          }
        />
        <Route
          path="/login"
          element={
            <motion.div variants={pageVariants} initial="initial" animate="animate" exit="exit" className="w-full">
              <AuthPage initialMode="login" />
            </motion.div>
          }
        />
        <Route
          path="/signup"
          element={
            <motion.div variants={pageVariants} initial="initial" animate="animate" exit="exit" className="w-full">
              <AuthPage initialMode="signup" />
            </motion.div>
          }
        />
        {/* Kept so existing links still land on the explainer, now a band on the landing page. */}
        <Route path="/how-it-works" element={<Navigate to="/#how-it-works" replace />} />
        <Route
          path="/admin"
          element={
            <motion.div variants={pageVariants} initial="initial" animate="animate" exit="exit" className="w-full">
              <RequireAuth requireAdmin>
                <AdminRoute />
              </RequireAuth>
            </motion.div>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AnimatePresence>
  );
}

const Router = import.meta.env.VITE_HASH_ROUTER === "1" ? HashRouter : BrowserRouter;

export default function App() {
  return (
    <ThemeProvider>
      <AmbientRadar />
      <Router>
        <ScrollToTop />
        <AnimatedRoutes />
      </Router>
    </ThemeProvider>
  );
}


