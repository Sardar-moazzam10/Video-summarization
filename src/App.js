import React, { useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import './App.css';
import Navbar from './Navbar.js';
import ChoicePage from './ChoicePage.js';
import SearchPage from './SearchPage.js';
import SearchByKeywordsPage from './SearchByKeywordsPage.js';
import TestTranscriptPage from './TestTranscriptPage.js';
import TranscriptViewer from './TranscriptViewer.js';
import SuggestedPodcastsPage from "./SuggestedPodcastsPage.js";
import SummarizedPlayer from "./SummarizedPlayer.js";
import MergePreviewPage from "./MergePreviewPage.js";
import LoginPage from './pages/LoginPage.js';
import SignupPage from './pages/SignupPage.js';
import ForgotPasswordPage from './pages/ForgotPasswordPage.js';
import VerifyCodePage from './pages/VerifyCodePage.js';
import ResetPasswordPage from './pages/ResetPasswordPage.js';
import VideoPlayerPage from './VideoPlayerPage.js';
import MergedPodcastPlayer from './MergedPodcastPlayer.js';
import TrimTestPage from './TrimTestPage.js';

// USER Panel Pages
import AccountInfoPage from './panel_pages/AccountInfoPage.js';
import SecurityPage from './panel_pages/SecurityPage.js';
import HistoryPage from './panel_pages/HistoryPage.js';

// ADMIN Panel Pages
import AdminAccountInfoPage from './admin_pages/AdminAccountInfoPage.js';
import AdminSecurityPage from './admin_pages/AdminSecurityPage.js';
import AdminHistoryPage from './admin_pages/AdminHistoryPage.js';
import AdminUserListPage from './admin_pages/AdminUserListPage.js';

import Footer from './Footer.js';
import ProtectedRoute from './ProtectedRoute.js';
import ContactPage from './ContactPage.js';
import AboutPage from './AboutPage.js';
import AssistantWidget from './AssistantWidget.js';


// Automatically redirect based on login status
const RedirectWrapper = () => {
  const location = useLocation();
  const isLoggedIn = localStorage.getItem("user");

  useEffect(() => {
    // Temporarily disabled redirect for testing frontend
    // if (!isLoggedIn && location.pathname === "/") {
    //   window.location.replace("/login");
    // }
  }, [isLoggedIn, location.pathname]);

  return null;
};

// Redirect user/admin to their correct dashboard
const RoleRedirect = () => {
  const navigate = useNavigate();
  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user'));
    if (user?.role === 'admin') {
      navigate('/admin-account-info');
    } else {
      navigate('/account-info');
    }
  }, [navigate]);
  return null;
};

const App = () => {
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const handleMouse = (e) => {
      setMousePos({ x: e.clientX, y: e.clientY });
    };
    window.addEventListener('mousemove', handleMouse);
    return () => window.removeEventListener('mousemove', handleMouse);
  }, []);

  return (
    <Router>
      <div
        className="ambient-glow"
        style={{
          background: `radial-gradient(800px circle at ${mousePos.x}px ${mousePos.y}px, rgba(71, 139, 224, 0.06), transparent 40%)`,
        }}
      />
      <RedirectWrapper />
      <Navbar />
      <Routes>
        {/* PUBLIC PAGES — accessible without login */}
        <Route path="/" element={<ChoicePage />} />
        <Route path="/contact" element={<ContactPage />} />
        <Route path="/about" element={<AboutPage />} />

        {/* PROTECTED PAGES — login required */}
        <Route path="/search-by-title" element={<ProtectedRoute allowedRoles={['user', 'admin']}><SearchPage /></ProtectedRoute>} />
        <Route path="/search-by-keywords" element={<ProtectedRoute allowedRoles={['user', 'admin']}><SearchByKeywordsPage /></ProtectedRoute>} />
        <Route path="/search/:query" element={<ProtectedRoute allowedRoles={['user', 'admin']}><SearchByKeywordsPage /></ProtectedRoute>} />
        <Route path="/transcript-viewer" element={<ProtectedRoute allowedRoles={['user', 'admin']}><TranscriptViewer /></ProtectedRoute>} />
        <Route path="/transcript-viewer/:videoId" element={<ProtectedRoute allowedRoles={['user', 'admin']}><TranscriptViewer /></ProtectedRoute>} />
        <Route path="/suggested-podcasts" element={<ProtectedRoute allowedRoles={['user', 'admin']}><SuggestedPodcastsPage /></ProtectedRoute>} />
        <Route path="/summarized-player" element={<ProtectedRoute allowedRoles={['user', 'admin']}><SummarizedPlayer /></ProtectedRoute>} />
        <Route path="/merge-preview" element={<ProtectedRoute allowedRoles={['user', 'admin']}><MergePreviewPage /></ProtectedRoute>} />
        <Route path="/video-player" element={<ProtectedRoute allowedRoles={['user', 'admin']}><VideoPlayerPage /></ProtectedRoute>} />
        <Route path="/video-player/:videoId" element={<ProtectedRoute allowedRoles={['user', 'admin']}><VideoPlayerPage /></ProtectedRoute>} />
        <Route path="/merged-player/:mergeId" element={<ProtectedRoute allowedRoles={['user', 'admin']}><MergedPodcastPlayer /></ProtectedRoute>} />
        <Route path="/test-transcript" element={<ProtectedRoute allowedRoles={['user', 'admin']}><TestTranscriptPage /></ProtectedRoute>} />
        <Route path="/trim-test" element={<ProtectedRoute allowedRoles={['user', 'admin']}><TrimTestPage /></ProtectedRoute>} />



        {/* AUTH */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/verify-code" element={<VerifyCodePage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />

        {/* UNIVERSAL POST-LOGIN REDIRECT */}
        <Route path="/manage-account" element={<RoleRedirect />} />

        {/* USER PANEL ROUTES */}
        <Route path="/account-info" element={
          <ProtectedRoute allowedRoles={['user']}>
            <AccountInfoPage />
          </ProtectedRoute>
        } />
        <Route path="/security" element={
          <ProtectedRoute allowedRoles={['user']}>
            <SecurityPage />
          </ProtectedRoute>
        } />
        <Route path="/history" element={
          <ProtectedRoute allowedRoles={['user']}>
            <HistoryPage />
          </ProtectedRoute>
        } />

        {/* ADMIN PANEL ROUTES */}
        <Route path="/admin-account-info" element={
          <ProtectedRoute allowedRoles={['admin']}>
            <AdminAccountInfoPage />
          </ProtectedRoute>
        } />
        <Route path="/admin-security" element={
          <ProtectedRoute allowedRoles={['admin']}>
            <AdminSecurityPage />
          </ProtectedRoute>
        } />
        <Route path="/admin-history" element={
          <ProtectedRoute allowedRoles={['admin']}>
            <AdminHistoryPage />
          </ProtectedRoute>
        } />
        <Route path="/admin-users" element={
          <ProtectedRoute allowedRoles={['admin']}>
            <AdminUserListPage />
          </ProtectedRoute>
        } />

        {/* UNKNOWN ROUTES */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
      <AssistantWidget />
      <Footer />
    </Router>
  );
};

export default App;
