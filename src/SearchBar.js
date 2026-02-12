import React, { useState } from 'react';

const SearchBar = ({ onSearch }) => {
  const [query, setQuery] = useState('');

  const handleSearch = () => {
    if (query.trim()) {
      onSearch(query);
      setQuery('');
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') handleSearch();
  };

  return (
    <div style={styles.container}>
      <div style={styles.inputWrap}>
        <svg style={styles.icon} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input
          type="text"
          placeholder="Search for videos..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyPress}
          style={styles.input}
        />
      </div>
      <button onClick={handleSearch} style={styles.button}>
        Search
      </button>
    </div>
  );
};

const styles = {
  container: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: '10px',
    marginBottom: '30px',
    maxWidth: '700px',
    marginLeft: 'auto',
    marginRight: 'auto',
  },
  inputWrap: {
    flex: 1,
    minWidth: '280px',
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
  },
  icon: {
    position: 'absolute',
    left: '14px',
    color: 'rgba(255,255,255,0.3)',
    pointerEvents: 'none',
  },
  input: {
    width: '100%',
    boxSizing: 'border-box',
    height: '48px',
    padding: '0 16px 0 42px',
    fontSize: '14px',
    borderRadius: '12px',
    border: '1px solid rgba(255,255,255,0.08)',
    background: 'rgba(255,255,255,0.04)',
    color: '#fff',
    fontFamily: 'inherit',
    outline: 'none',
    transition: 'border-color 0.2s',
  },
  button: {
    boxSizing: 'border-box',
    height: '48px',
    padding: '0 28px',
    fontSize: '14px',
    fontWeight: 600,
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    border: 'none',
    borderRadius: '12px',
    cursor: 'pointer',
    fontFamily: 'inherit',
    lineHeight: '1',
    whiteSpace: 'nowrap',
    boxShadow: '0 2px 10px rgba(71,139,224,0.25)',
    transition: 'all 0.2s',
  },
};

export default SearchBar;
