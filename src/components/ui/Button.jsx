import React from 'react';
import { motion } from 'framer-motion';
import './Button.css';

/**
 * Universal Button Component
 * Supports: primary, secondary, tertiary, danger
 * States: default, loading, disabled, icon-only
 */
const Button = ({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  icon = null,
  iconPosition = 'left',
  fullWidth = false,
  type = 'button',
  onClick,
  className = '',
  ...props
}) => {
  return (
    <motion.button
      className={`btn btn-${variant} btn-${size} ${fullWidth ? 'btn-full-width' : ''} ${className}`}
      disabled={disabled || loading}
      type={type}
      onClick={onClick}
      whileHover={{ y: disabled || loading ? 0 : -2 }}
      whileTap={{ y: disabled || loading ? 0 : 0 }}
      transition={{ type: 'spring', stiffness: 400, damping: 17 }}
      {...props}
    >
      {loading && (
        <svg
          className="btn-spinner"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <circle cx="12" cy="12" r="10" opacity="0.25" />
          <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round" />
        </svg>
      )}
      {icon && iconPosition === 'left' && !loading && <span className="btn-icon">{icon}</span>}
      <span>{loading ? 'Loading...' : children}</span>
      {icon && iconPosition === 'right' && !loading && <span className="btn-icon">{icon}</span>}
    </motion.button>
  );
};

export default Button;
