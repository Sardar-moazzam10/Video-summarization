import React, { useRef, useState, useEffect, useCallback } from 'react';
import { punctuateText } from './utils/punctuateText.js';

const TrimTestPage = () => {
  const [videoInputs, setVideoInputs] = useState([{ url: '' }, { url: '' }]);
  const [segments, setSegments] = useState([]);
  const [mergedTime, setMergedTime] = useState(0);
  const [loading, setLoading] = useState(false);
  const [durationsReady, setDurationsReady] = useState(false);
  const [readyToPlay, setReadyToPlay] = useState(false);
  const [combinedTranscript, setCombinedTranscript] = useState('');

  const totalDurationRef = useRef(0);
  const intervalRef = useRef(null);
  const playerRef = useRef(null);
  const synthRef = useRef(window.speechSynthesis);
  const utteranceRef = useRef(null);

  const extractVideoId = (url) => {
    const regex = /(?:youtube\.com\/.*v=|youtu\.be\/)([^&\n?#]+)/;
    const match = url.match(regex);
    return match ? match[1] : '';
  };

  const handleInputChange = (index, value) => {
    const updated = [...videoInputs];
    updated[index].url = value;
    setVideoInputs(updated);
  };

  const addInputField = () => {
    setVideoInputs([...videoInputs, { url: '' }]);
  };

  const loadYouTubeAPI = () => {
    return new Promise((resolve) => {
      if (window.YT && window.YT.Player) resolve();
      else {
        const tag = document.createElement("script");
        tag.src = "https://www.youtube.com/iframe_api";
        document.body.appendChild(tag);
        window.onYouTubeIframeAPIReady = resolve;
      }
    });
  };

  const getDurations = (videoIds) => {
    return new Promise((resolve) => {
      const durations = [];
      let loaded = 0;
      const loadNext = (i) => {
        const tempPlayer = new window.YT.Player(`hidden-player-${i}`, {
          videoId: videoIds[i],
          events: {
            onReady: () => {
              durations[i] = tempPlayer.getDuration();
              tempPlayer.destroy();
              loaded++;
              if (loaded === videoIds.length) resolve(durations);
              else loadNext(i + 1);
            }
          }
        });
      };
      loadNext(0);
    });
  };

  const speakText = (text) => {
    const synth = synthRef.current;
    synth.cancel(); // stop anything already speaking

    const voices = synth.getVoices();
    const selectedVoice = voices.find(v => v.name.includes("Google") || v.name.includes("Samantha") || v.name.includes("Microsoft")) || voices[0];

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = selectedVoice;
    utterance.rate = 0.9;
    utterance.pitch = 1.1;
    utterance.volume = 1;

    utteranceRef.current = utterance;
    synth.speak(utterance);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    await loadYouTubeAPI();

    const videoIds = videoInputs.map(v => extractVideoId(v.url)).filter(Boolean);
    if (videoIds.length < 2) {
      alert("Please enter at least 2 valid YouTube URLs.");
      return;
    }

    setLoading(true);

    const durations = await getDurations(videoIds);
    const segs = await Promise.all(videoIds.map(async (videoId, i) => {
      const duration = durations[i];
      const maxStart = Math.max(0, duration - 300);
      const minStart = Math.floor(duration * 0.2);
      const start = Math.floor(Math.random() * (maxStart - minStart + 1) + minStart);
      const end = Math.min(start + 300, duration);

      const transcriptResponse = await fetch(`http://localhost:8000/api/v1/transcript?videoId=${videoId}`);
      const transcriptData = await transcriptResponse.json();

      const rawSegmentText = transcriptData
        .filter(item => item.start >= start && item.start <= end)
        .map(item => item.text)
        .join(' ');

      const punctuated = await punctuateText(rawSegmentText);
      return { videoId, start, end, duration: end - start, transcript: punctuated };
    }));

    const total = segs.reduce((sum, seg) => sum + seg.duration, 0);
    totalDurationRef.current = total;
    setSegments(segs);
    const fullTranscript = segs.map(s => s.transcript).join(' ');
    setCombinedTranscript(fullTranscript);

    speakText(fullTranscript);
    setDurationsReady(true);
    setLoading(false);
  };

  useEffect(() => {
    return () => clearInterval(intervalRef.current);
  }, []);

useEffect(() => {
  if (durationsReady) loadPlayer();
}, [durationsReady, loadPlayer]);

  const loadPlayer = useCallback(() => {
    const firstSegment = segments[0];
    playerRef.current = new window.YT.Player('ytplayer', {
      height: '390',
      width: '640',
      videoId: firstSegment.videoId,
      playerVars: { controls: 0, modestbranding: 1, rel: 0, showinfo: 0, fs: 0 },
      events: {
        onReady: () => {
          setTimeout(() => {
            setReadyToPlay(true);
            playSegment(0);
          }, 1000);
        }
      }
    });
  }, [segments]);

  const playSegment = (index) => {
    clearInterval(intervalRef.current);
    const segment = segments[index];
    if (!segment || !playerRef.current) return;
    playerRef.current.loadVideoById({
      videoId: segment.videoId,
      startSeconds: segment.start,
      endSeconds: segment.end
    });

    playerRef.current.mute();

    intervalRef.current = setInterval(() => {
      const currentTime = playerRef.current.getCurrentTime();
      const relative = currentTime - segment.start;
      const before = segments.slice(0, index).reduce((sum, s) => sum + s.duration, 0);
      setMergedTime(before + relative);

      if (currentTime >= segment.end - 0.3) {
        clearInterval(intervalRef.current);
        if (index + 1 < segments.length) playSegment(index + 1);
      }
    }, 200);
  };

  const handleSliderChange = (e) => {
    const globalTarget = (totalDurationRef.current * Number(e.target.value)) / 100;
    let accumulated = 0;
    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      const segStartInMerged = accumulated;
      const segEndInMerged = accumulated + seg.duration;
      if (globalTarget >= segStartInMerged && globalTarget <= segEndInMerged) {
        const seekTo = seg.start + (globalTarget - segStartInMerged);
        playerRef.current.loadVideoById({ videoId: seg.videoId, startSeconds: seekTo, endSeconds: seg.end });
        setMergedTime(globalTarget);
        break;
      }
      accumulated += seg.duration;
    }
  };

  const getSliderValue = () => {
    const val = (mergedTime / totalDurationRef.current) * 100;
    return isNaN(val) ? 0 : val;
  };

  const handlePlay = () => {
    if (playerRef.current) playerRef.current.playVideo();
    if (utteranceRef.current) synthRef.current.resume();
  };

  const handlePause = () => {
    if (playerRef.current) playerRef.current.pauseVideo();
    if (utteranceRef.current) synthRef.current.pause();
  };

  const handleReplay = () => {
    if (utteranceRef.current) synthRef.current.cancel();
    speakText(combinedTranscript);
    playSegment(0);
  };

  return (
    <div style={{ padding: '20px', backgroundColor: '#111', color: '#fff', minHeight: '100vh' }}>
      <h2>🎬 Merged YouTube Player with AI Voiceover</h2>
      <form onSubmit={handleSubmit}>
        {videoInputs.map((input, index) => (
          <div key={index} style={{ marginBottom: '10px' }}>
            <input
              type="text"
              placeholder="YouTube URL"
              value={input.url}
              onChange={(e) => handleInputChange(index, e.target.value)}
              style={{ padding: '8px', width: '400px' }}
            />
          </div>
        ))}
        <button type="button" onClick={addInputField} style={buttonStyle}>➕ Add Another</button>
        <button type="submit" style={{ ...buttonStyle, marginLeft: '10px' }}>🎞️ Merge & Play</button>
      </form>

      <div id="ytplayer" style={{ margin: '30px 0', pointerEvents: 'none' }}></div>
      <div style={{ display: 'none' }}>{videoInputs.map((_, i) => (<div key={i} id={`hidden-player-${i}`} />))}</div>

      {loading && (
        <div style={loaderStyle}>
          <div className="spinner" />
          <p style={{ marginTop: '12px', color: '#aaa' }}>⏳ Preparing voice & video, please wait...</p>
        </div>
      )}

      {readyToPlay && segments.length > 0 && (
        <>
          <div style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
            <button onClick={handlePlay} style={buttonStyle}>▶️ Play</button>
            <button onClick={handlePause} style={buttonStyle}>⏸ Pause</button>
            <button onClick={handleReplay} style={buttonStyle}>🔁 Replay</button>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            value={getSliderValue()}
            onChange={handleSliderChange}
            style={{ width: '640px' }}
          />
          <p style={{ textAlign: 'center', color: '#aaa' }}>
            Global Time: {Math.floor(mergedTime)}s / {totalDurationRef.current}s
          </p>
          <div style={{ marginTop: '20px', color: '#ccc', fontSize: '16px', lineHeight: '1.5' }}>
            <strong>🗣 Transcript:</strong> {combinedTranscript}
          </div>
        </>
      )}
    </div>
  );
};

const buttonStyle = {
  padding: '10px 16px',
  backgroundColor: '#8B5DFF',
  color: '#fff',
  border: 'none',
  cursor: 'pointer',
  borderRadius: '6px'
};

const loaderStyle = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  marginTop: '30px'
};

const styleTag = document.createElement("style");
styleTag.innerHTML = `
.spinner {
  width: 40px;
  height: 40px;
  border: 5px solid #8B5DFF;
  border-top: 5px solid transparent;
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
`;
document.head.appendChild(styleTag);

export default TrimTestPage;
