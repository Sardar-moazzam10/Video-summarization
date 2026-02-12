/**
 * Core UI Components - Recall.ai Inspired Design System
 * Premium dark theme with blue accents and smooth animations
 */

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';

// ============================================
// GRADIENT TEXT
// ============================================
export const GradientText = ({ children, className = "", as: Component = "span" }) => (
  <Component
    className={`
      bg-gradient-to-r from-brand-500 via-brand-400 to-white
      bg-clip-text text-transparent
      ${className}
    `}
  >
    {children}
  </Component>
);

// ============================================
// CARD
// ============================================
export const Card = ({
  children,
  className = "",
  glow = false,
  hover = true,
  padding = "p-6",
  ...props
}) => (
  <motion.div
    className={`
      bg-surface-elevated rounded-2xl
      border border-white/10
      backdrop-blur-sm
      transition-all duration-300
      ${hover ? 'hover:border-brand-500/30 hover:bg-surface-elevated/80' : ''}
      ${glow ? 'shadow-lg shadow-brand-500/20 hover:shadow-brand-500/30' : ''}
      ${padding}
      ${className}
    `}
    whileHover={hover ? { y: -2 } : {}}
    {...props}
  >
    {children}
  </motion.div>
);

// ============================================
// BUTTON
// ============================================
export const Button = ({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  icon = null,
  iconPosition = "left",
  className = "",
  ...props
}) => {
  const variants = {
    primary: `
      bg-gradient-to-r from-brand-600 to-brand-500
      hover:from-brand-500 hover:to-brand-400
      text-white shadow-lg shadow-brand-500/25
      hover:shadow-brand-500/40
    `,
    secondary: `
      bg-white/5 hover:bg-white/10
      text-white border border-white/10
      hover:border-white/20
    `,
    ghost: `
      hover:bg-white/5
      text-content-secondary hover:text-white
    `,
    danger: `
      bg-error/10 hover:bg-error/20
      text-error border border-error/20
    `,
  };

  const sizes = {
    sm: "px-4 py-2 text-sm gap-1.5",
    md: "px-6 py-3 text-base gap-2",
    lg: "px-8 py-4 text-lg gap-2.5",
    xl: "px-10 py-5 text-xl gap-3",
  };

  return (
    <motion.button
      className={`
        ${variants[variant]}
        ${sizes[size]}
        rounded-xl font-medium
        transition-all duration-200
        disabled:opacity-50 disabled:cursor-not-allowed
        flex items-center justify-center
        ${className}
      `}
      whileHover={{ scale: loading ? 1 : 1.02 }}
      whileTap={{ scale: loading ? 1 : 0.98 }}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading ? (
        <>
          <Spinner size={size === "sm" ? 16 : 20} />
          <span>Processing...</span>
        </>
      ) : (
        <>
          {icon && iconPosition === "left" && icon}
          {children}
          {icon && iconPosition === "right" && icon}
        </>
      )}
    </motion.button>
  );
};

// ============================================
// SPINNER
// ============================================
export const Spinner = ({ size = 20, className = "" }) => (
  <svg
    className={`animate-spin ${className}`}
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
  >
    <circle
      className="opacity-25"
      cx="12"
      cy="12"
      r="10"
      stroke="currentColor"
      strokeWidth="4"
    />
    <path
      className="opacity-75"
      fill="currentColor"
      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
    />
  </svg>
);

// ============================================
// PROGRESS RING
// ============================================
export const ProgressRing = ({
  progress,
  size = 120,
  strokeWidth = 8,
  showLabel = true,
  className = "",
}) => {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (progress / 100) * circumference;

  return (
    <div className={`relative ${className}`} style={{ width: size, height: size }}>
      <svg className="transform -rotate-90" width={size} height={size}>
        {/* Background circle */}
        <circle
          className="text-white/10"
          strokeWidth={strokeWidth}
          stroke="currentColor"
          fill="transparent"
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
        {/* Progress circle */}
        <motion.circle
          className="text-brand-500"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          strokeLinecap="round"
          stroke="currentColor"
          fill="transparent"
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
      </svg>

      {/* Center content */}
      {showLabel && (
        <div className="absolute inset-0 flex items-center justify-center">
          <motion.span
            className="text-2xl font-bold text-white"
            key={Math.round(progress)}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.2 }}
          >
            {Math.round(progress)}%
          </motion.span>
        </div>
      )}

      {/* Pulse ring */}
      <motion.div
        className="absolute inset-0 rounded-full border-2 border-brand-500/30"
        animate={{
          scale: [1, 1.2, 1],
          opacity: [0.5, 0, 0.5],
        }}
        transition={{
          duration: 2,
          repeat: Infinity,
          ease: "easeInOut",
        }}
      />
    </div>
  );
};

// ============================================
// INPUT
// ============================================
export const Input = ({
  label,
  error,
  icon,
  className = "",
  ...props
}) => (
  <div className={`space-y-2 ${className}`}>
    {label && (
      <label className="block text-sm font-medium text-content-secondary">
        {label}
      </label>
    )}
    <div className="relative">
      {icon && (
        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-content-tertiary">
          {icon}
        </div>
      )}
      <input
        className={`
          w-full px-4 py-3 rounded-xl
          bg-white/5 border border-white/10
          text-white placeholder-content-tertiary
          focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500
          transition-all duration-200
          ${icon ? 'pl-12' : ''}
          ${error ? 'border-error focus:ring-error/50 focus:border-error' : ''}
        `}
        {...props}
      />
    </div>
    {error && (
      <p className="text-sm text-error">{error}</p>
    )}
  </div>
);

// ============================================
// BADGE
// ============================================
export const Badge = ({
  children,
  variant = "default",
  size = "md",
  className = "",
}) => {
  const variants = {
    default: "bg-white/10 text-content-secondary",
    brand: "bg-brand-500/20 text-brand-400",
    success: "bg-success/20 text-success",
    warning: "bg-warning/20 text-warning",
    error: "bg-error/20 text-error",
  };

  const sizes = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-3 py-1 text-sm",
    lg: "px-4 py-1.5 text-base",
  };

  return (
    <span
      className={`
        inline-flex items-center rounded-full font-medium
        ${variants[variant]}
        ${sizes[size]}
        ${className}
      `}
    >
      {children}
    </span>
  );
};

// ============================================
// SKELETON
// ============================================
export const Skeleton = ({
  className = "",
  variant = "rectangular",
  width,
  height,
}) => {
  const variants = {
    rectangular: "rounded-lg",
    circular: "rounded-full",
    text: "rounded h-4",
  };

  return (
    <div
      className={`
        bg-white/5 animate-pulse
        ${variants[variant]}
        ${className}
      `}
      style={{ width, height }}
    />
  );
};

// ============================================
// TOAST
// ============================================
export const Toast = ({ message, type = "info", onClose }) => {
  const types = {
    success: { bg: "bg-success/20", border: "border-success/30", icon: "✓" },
    error: { bg: "bg-error/20", border: "border-error/30", icon: "✕" },
    warning: { bg: "bg-warning/20", border: "border-warning/30", icon: "!" },
    info: { bg: "bg-info/20", border: "border-info/30", icon: "i" },
  };

  const style = types[type];

  return (
    <motion.div
      initial={{ opacity: 0, y: 50, scale: 0.9 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 20, scale: 0.9 }}
      className={`
        flex items-center gap-3 px-4 py-3 rounded-xl
        ${style.bg} border ${style.border}
        backdrop-blur-sm shadow-lg
      `}
    >
      <span className="w-6 h-6 rounded-full bg-white/10 flex items-center justify-center text-sm">
        {style.icon}
      </span>
      <p className="text-white flex-1">{message}</p>
      <button
        onClick={onClose}
        className="text-content-tertiary hover:text-white transition-colors"
      >
        ✕
      </button>
    </motion.div>
  );
};

// ============================================
// TOOLTIP
// ============================================
export const Tooltip = ({ children, content, position = "top" }) => {
  const [show, setShow] = React.useState(false);

  const positions = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
    left: "right-full top-1/2 -translate-y-1/2 mr-2",
    right: "left-full top-1/2 -translate-y-1/2 ml-2",
  };

  return (
    <div
      className="relative inline-block"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      <AnimatePresence>
        {show && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className={`
              absolute z-50 px-3 py-2 rounded-lg
              bg-surface-card border border-white/10
              text-sm text-white whitespace-nowrap
              shadow-lg
              ${positions[position]}
            `}
          >
            {content}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

// ============================================
// MODAL
// ============================================
export const Modal = ({ isOpen, onClose, title, children, size = "md" }) => {
  const sizes = {
    sm: "max-w-md",
    md: "max-w-lg",
    lg: "max-w-2xl",
    xl: "max-w-4xl",
    full: "max-w-[95vw]",
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className={`
              fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2
              w-full ${sizes[size]} z-50
              bg-surface-card rounded-2xl border border-white/10
              shadow-2xl
            `}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-white/10">
              <h2 className="text-xl font-semibold text-white">{title}</h2>
              <button
                onClick={onClose}
                className="w-8 h-8 rounded-lg bg-white/5 hover:bg-white/10 flex items-center justify-center text-content-tertiary hover:text-white transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Content */}
            <div className="p-6">
              {children}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};

// ============================================
// ICON BUTTON
// ============================================
export const IconButton = ({
  children,
  variant = "ghost",
  size = "md",
  className = "",
  ...props
}) => {
  const variants = {
    ghost: "hover:bg-white/10 text-content-secondary hover:text-white",
    filled: "bg-white/10 hover:bg-white/20 text-white",
    brand: "bg-brand-500/20 hover:bg-brand-500/30 text-brand-400",
  };

  const sizes = {
    sm: "w-8 h-8",
    md: "w-10 h-10",
    lg: "w-12 h-12",
  };

  return (
    <motion.button
      className={`
        ${variants[variant]}
        ${sizes[size]}
        rounded-xl flex items-center justify-center
        transition-colors duration-200
        ${className}
      `}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.95 }}
      {...props}
    >
      {children}
    </motion.button>
  );
};

// ============================================
// DIVIDER
// ============================================
export const Divider = ({ className = "" }) => (
  <div className={`h-px bg-white/10 ${className}`} />
);

// ============================================
// CONTAINER
// ============================================
export const Container = ({ children, size = "default", className = "" }) => {
  const sizes = {
    sm: "max-w-3xl",
    default: "max-w-6xl",
    lg: "max-w-7xl",
    full: "max-w-full",
  };

  return (
    <div className={`mx-auto px-4 sm:px-6 lg:px-8 ${sizes[size]} ${className}`}>
      {children}
    </div>
  );
};

export default {
  GradientText,
  Card,
  Button,
  Spinner,
  ProgressRing,
  Input,
  Badge,
  Skeleton,
  Toast,
  Tooltip,
  Modal,
  IconButton,
  Divider,
  Container,
};
