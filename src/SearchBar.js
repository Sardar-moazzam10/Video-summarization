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
      <input
        type="text"
        placeholder="Search for videos..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyPress}
        style={styles.input}
      />
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
    maxWidth: '800px',
    marginLeft: 'auto',
    marginRight: 'auto',
  },
  input: {
    boxSizing: 'border-box',
    height: '48px',
    padding: '0 16px',
    fontSize: '16px',
    borderRadius: '8px',
    border: '1px solid #ccc',
    minWidth: '320px',
    lineHeight: '1',
  },
  button: {
    boxSizing: 'border-box',
    height: '48px',
    padding: '0 24px',
    fontSize: '16px',
    fontWeight: 'bold',
    backgroundColor: '#0EA5E9',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    cursor: 'pointer',
    lineHeight: '1',
    whiteSpace: 'nowrap',
  },
};

export default SearchBar;
