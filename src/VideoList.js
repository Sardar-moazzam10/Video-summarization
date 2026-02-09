import React from 'react';
import VideoCard from './VideoCard.js';

const VideoList = ({ videos, selectedVideoIds = [], onToggleSelectForMerge }) => {
  return (
    <div style={styles.container}>
      <div style={styles.grid}>
        {videos.map((video) => {
          const id = video.id?.videoId || video.id;
          return (
            <VideoCard
              key={id}
              video={video}
              videosList={videos}
              isSelected={selectedVideoIds.includes(id)}
              onToggleSelectForMerge={onToggleSelectForMerge}
            />
          );
        })}
      </div>
    </div>
  );
};

const styles = {
  container: {
    maxWidth: '1200px',
    margin: '0 auto',
    padding: '20px',
  },
  grid: {
    display: 'flex',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: '30px',
  },
};

export default VideoList;
