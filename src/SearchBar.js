import React, { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const SearchBar = ({ onSearch, placeholder = 'Search for videos...' }) => {
  const [query, setQuery] = useState('');
  const [focused, setFocused] = useState(false);
  const inputRef = useRef(null);

  const handleSearch = () => {
    const trimmed = query.trim();
    if (trimmed) {
      onSearch(trimmed);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSearch();
    if (e.key === 'Escape') { setQuery(''); inputRef.current?.blur(); }
  };

  const handleClear = () => {
    setQuery('');
    inputRef.current?.focus();
  };

  return (
    <div className={`sb-wrap ${focused ? 'sb-wrap--focused' : ''}`}>
      {/* Search icon */}
      <svg className="sb-icon-search" width="18" height="18" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
      </svg>

      <input
        ref={inputRef}
        type="text"
        className="sb-input"
        placeholder={placeholder}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
      />

      {/* Clear button */}
      <AnimatePresence>
        {query && (
          <motion.button
            className="sb-clear"
            onClick={handleClear}
            initial={{ opacity: 0, scale: 0.7 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.7 }}
            transition={{ duration: 0.15 }}
            type="button"
            aria-label="Clear search"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2.5" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </motion.button>
        )}
      </AnimatePresence>

      <motion.button
        className="sb-btn"
        onClick={handleSearch}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.97 }}
        type="button"
      >
        Search
      </motion.button>

      <style>{`
        .sb-wrap {
          display: flex;
          align-items: center;
          gap: 10px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 14px;
          padding: 6px 6px 6px 14px;
          transition: border-color 0.2s, box-shadow 0.2s;
          position: relative;
        }
        .sb-wrap--focused {
          border-color: rgba(71,139,224,0.5);
          box-shadow: 0 0 0 3px rgba(71,139,224,0.1);
        }
        .sb-icon-search {
          color: rgba(255,255,255,0.3);
          flex-shrink: 0;
        }
        .sb-wrap--focused .sb-icon-search {
          color: rgba(71,139,224,0.7);
        }
        .sb-input {
          flex: 1;
          background: none;
          border: none;
          outline: none;
          color: #fff;
          font-size: 14.5px;
          font-family: inherit;
          min-width: 0;
        }
        .sb-input::placeholder {
          color: rgba(255,255,255,0.25);
        }
        .sb-clear {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 24px;
          height: 24px;
          border-radius: 50%;
          background: rgba(255,255,255,0.08);
          border: none;
          color: rgba(255,255,255,0.5);
          cursor: pointer;
          flex-shrink: 0;
          transition: background 0.15s, color 0.15s;
          padding: 0;
        }
        .sb-clear:hover {
          background: rgba(255,255,255,0.14);
          color: #fff;
        }
        .sb-btn {
          flex-shrink: 0;
          padding: 9px 22px;
          background: linear-gradient(135deg, #478BE0, #2F61A0);
          color: #fff;
          border: none;
          border-radius: 10px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          font-family: inherit;
          box-shadow: 0 2px 8px rgba(71,139,224,0.25);
          transition: box-shadow 0.2s;
          min-height: 38px;
        }
        .sb-btn:hover {
          box-shadow: 0 4px 16px rgba(71,139,224,0.4);
        }
        @media (max-width: 480px) {
          .sb-wrap { border-radius: 12px; padding: 5px 5px 5px 12px; }
          .sb-btn { padding: 8px 16px; font-size: 13px; }
        }
      `}</style>
    </div>
  );
};

export default SearchBar;
