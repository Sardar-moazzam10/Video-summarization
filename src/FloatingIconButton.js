import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './FloatingIconButton.css';

const FloatingIconButton = () => {
    const navigate = useNavigate();
    const [showTooltip, setShowTooltip] = useState(false);

    const handleClick = () => {
        navigate('/');
    };

    return (
        <div
            className="floating-icon-container"
            onMouseEnter={() => setShowTooltip(true)}
            onMouseLeave={() => setShowTooltip(false)}
            onClick={handleClick}
        >
            <div className="floating-icon-button">
                <img
                    src={`${process.env.PUBLIC_URL}/video_summarizer_icon.png`}
                    alt="Video Summarizer"
                />
            </div>
            {showTooltip && (
                <div className="floating-tooltip">
                    Video Summarizer
                </div>
            )}
        </div>
    );
};

export default FloatingIconButton;
