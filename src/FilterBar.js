import React from 'react';

const FilterBar = ({ onFilterChange }) => {
  return (
    <div style={{ margin: '20px', display: 'flex', justifyContent: 'center' }}>
      <button onClick={() => onFilterChange('long')} style={buttonStyle}>
        Long Videos
      </button>
      <button onClick={() => onFilterChange('medium')} style={buttonStyle}>
        Medium Videos
      </button>
      <button onClick={() => onFilterChange('short')} style={buttonStyle}>
        Short Videos
      </button>
    </div>
  );
};

const buttonStyle = {
  padding: '10px 20px',
  margin: '0 10px',
  backgroundColor: '#007bff',
  color: '#fff',
  border: 'none',
  borderRadius: '5px',
  cursor: 'pointer',
};

export default FilterBar;
