import React from 'react';
import { render, screen } from '@testing-library/react';
import TrimTestPage from './TrimTestPage.js';

// Mock speech synthesis
beforeAll(() => {
  window.speechSynthesis = {
    cancel: jest.fn(),
    speak: jest.fn(),
    resume: jest.fn(),
    pause: jest.fn(),
    getVoices: jest.fn(() => []),
  };
});

describe('TrimTestPage component mount', () => {
  test('renders without crashing on mount (no TDZ ReferenceError)', () => {
    render(<TrimTestPage />);
    expect(screen.getByText(/Merged YouTube Player with AI Voiceover/i)).toBeInTheDocument();
    expect(screen.getByText(/Merge & Play/i)).toBeInTheDocument();
  });
});
