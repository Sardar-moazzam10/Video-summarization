import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios'; // Assuming axios for HTTP requests
import { API_BASE_URL } from '../config'; // Assuming a config file for base URL
import './JobStatusPage.css'; // Create this CSS file for styling

const JobStatusPage = () => {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState('pending');
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState('Starting job...');
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!jobId) {
      setError('No job ID provided.');
      return;
    }

    const eventSource = new EventSource(`${API_BASE_URL}/merge/${jobId}/stream`);

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setStatus(data.status);
      setProgress(data.progress_percent);
      setMessage(data.stage_message);

      if (data.status === 'completed' || data.status === 'partial_success') {
        eventSource.close();
        // Fetch the final result to get the video URL and other details
        axios.get(`${API_BASE_URL}/merge/${jobId}/result`)
          .then(response => {
            const videoUrl = response.data.video_url;
            if (videoUrl) {
              // Redirect to the player page, passing job_id and full job details
              navigate(`/merged-player/${jobId}`, { state: { jobDetails: response.data } });
            } else {
              setError('Video generated, but URL not found in result.');
            }
          })
          .catch(err => {
            console.error('Error fetching job result:', err);
            setError('Failed to retrieve video result.');
          });
      } else if (data.status === 'error') {
        eventSource.close();
        setError(data.error || 'An unknown error occurred during processing.');
      }
    };

    eventSource.onerror = (err) => {
      console.error('EventSource failed:', err);
      eventSource.close();
      setError('Connection to job progress stream lost or failed. Please check console for details.');
    };

    return () => {
      eventSource.close();
    };
  }, [jobId, navigate]);

  if (error) {
    return (
      <div className="job-status-container error">
        <h1>Error Generating Summary</h1>
        <p>{error}</p>
        <button onClick={() => navigate('/')}>Go Home</button>
      </div>
    );
  }

  return (
    <div className="job-status-container">
      <h1>Generating Your Video Summary</h1>
      <p>Job ID: {jobId}</p>
      <div className="progress-bar-wrapper">
        <div className="progress-bar" style={{ width: `${progress}%` }}></div>
      </div>
      <p className="progress-message">{message} ({progress}%)</p>
      {status === 'completed' && <p>Redirecting to your summarized video...</p>}
      {status === 'partial_success' && <p>Summary ready with some warnings. Redirecting...</p>}
    </div>
  );
};

export default JobStatusPage;
