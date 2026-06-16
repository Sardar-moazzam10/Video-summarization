import React from 'react';
import { motion } from 'framer-motion';
import VideoCard from './VideoCard.js';

const VideoList = ({ videos, selectedVideoIds = [], onToggleSelectForMerge }) => {
  if (!videos || videos.length === 0) return null;

  return (
    <div className="vl-container">
      <div className="vl-grid">
        {videos.map((video, idx) => {
          const id = video.id?.videoId || video.id;
          return (
            <motion.div
              key={id || idx}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: idx * 0.04 }}
            >
              <VideoCard
                video={video}
                videosList={videos}
                isSelected={selectedVideoIds.includes(id)}
                onToggleSelectForMerge={onToggleSelectForMerge}
              />
            </motion.div>
          );
        })}
      </div>

      <style>{`
        .vl-container {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 20px;
        }
        .vl-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
          gap: 20px;
        }
        @media (max-width: 640px) {
          .vl-grid {
            grid-template-columns: 1fr;
            gap: 16px;
          }
          .vl-container {
            padding: 0 16px;
          }
        }
      `}</style>
    </div>
  );
};

export default VideoList;
