import React, { useState, useRef, useEffect } from 'react';
import './AssistantWidget.css';

// =====================================================
// KNOWLEDGE BASE
// =====================================================

const INITIAL_OPTIONS = [
  "What does this app do?",
  "How does video summarization work?",
  "What AI models are used?",
  "How do I get started?",
];

const KNOWLEDGE_BASE = {
  "What does this app do?": {
    answer:
      "AI Video Summarizer lets you search for YouTube videos, extract transcripts, and generate AI-powered summaries complete with voice narration, video highlights, chapters, key takeaways, and more. You can merge multiple videos into one cohesive summary — like creating your own podcast from any YouTube content!",
    followUps: [
      "How does video summarization work?",
      "What features are included?",
      "How do I get started?",
    ],
  },
  "How does video summarization work?": {
    answer:
      "Here's the pipeline: First, we fetch video transcripts using YouTube's API (with Whisper AI fallback). Then, our fusion engine analyzes and combines content across videos. Gemini AI enriches the summary with chapters, takeaways, and quotes. Finally, Edge TTS generates voice narration, and FFmpeg creates video highlight reels. The whole process is automated — just pick your videos and hit merge!",
    followUps: [
      "What AI models are used?",
      "What about video highlights?",
      "Can I chat with videos?",
    ],
  },
  "What AI models are used?": {
    answer:
      "We use several AI models working together: **Gemini 2.0 Flash** for rich text summarization (chapters, quotes, TL;DR). **Gemini 3 Pro** with Thinking mode for native video understanding and highlight extraction. **BART-large-CNN** as a free fallback summarizer. **Sentence-BERT** (all-MiniLM-L6-v2) for semantic search and FAISS vector indexing. **Whisper** for speech-to-text when transcripts aren't available. All models are configured through our backend — no API keys needed from you!",
    followUps: [
      "How does video summarization work?",
      "What features are included?",
      "How do I get started?",
    ],
  },
  "How do I get started?": {
    answer:
      "It's easy! 1) **Sign up** for a free account (or sign in if you already have one). 2) Go to **Search** and find YouTube videos by title or keywords. 3) **Select 2+ videos** you want to summarize. 4) Click **Merge** — choose your duration, style, and optionally enable video highlights. 5) Wait for the AI pipeline to process (you'll see real-time progress). 6) **Enjoy** your summary with audio narration, chapters, key takeaways, and video highlights!",
    followUps: [
      "What does this app do?",
      "What features are included?",
      "What AI models are used?",
    ],
  },
  "What features are included?": {
    answer:
      "Here's everything you get: AI-generated summaries with TL;DR, chapters, key takeaways, best quotes, and action steps. Voice narration powered by Edge TTS (completely free). Video highlight reels using Gemini 3 Pro's native video analysis. Chat with Video — ask questions about your videos using semantic search. PDF and text export. Subtitle generation. Multi-video fusion into one cohesive summary. And it's all wrapped in a beautiful dark-mode interface!",
    followUps: [
      "What about video highlights?",
      "Can I chat with videos?",
      "How do I get started?",
    ],
  },
  "What about video highlights?": {
    answer:
      "When merging videos, toggle on 'Video Highlights' and pick a duration (1–5 min). Gemini 3 Pro uploads and watches your actual video files, using its Thinking mode to reason about the most compelling moments — key arguments, demos, dramatic reveals. It then outputs precise timestamps, and our FFmpeg pipeline trims, normalizes, and stitches the clips into a polished highlight reel. If Gemini is unavailable, it falls back to transcript-based selection.",
    followUps: [
      "What AI models are used?",
      "Can I chat with videos?",
      "How do I get started?",
    ],
  },
  "Can I chat with videos?": {
    answer:
      "Yes! After your videos are processed, you'll see a 'Chat with Video' section on the results page. Type any question about the video content and our system uses FAISS semantic search to find the most relevant transcript segments, then Gemini synthesizes a concise answer with source attributions. It's like having a conversation with your videos!",
    followUps: [
      "What features are included?",
      "How does video summarization work?",
      "How do I get started?",
    ],
  },
};

const WELCOME_MESSAGE =
  "Hey! I'm your AI Video Summarizer assistant. I can help you learn about the platform and how to get started. What would you like to know?";

// =====================================================
// HELPERS
// =====================================================

/** Render **bold** markdown in bot messages */
function renderBotText(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return <span key={i}>{part}</span>;
  });
}

// =====================================================
// COMPONENT
// =====================================================

const AssistantWidget = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [currentOptions, setCurrentOptions] = useState(INITIAL_OPTIONS);
  const [hasOpened, setHasOpened] = useState(false);

  const messagesEndRef = useRef(null);
  const panelRef = useRef(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isTyping]);

  // Open chat panel
  const handleOpen = () => {
    setIsOpen(true);
    if (!hasOpened) {
      setHasOpened(true);
      // Show welcome message on first open
      setMessages([{ role: 'bot', text: WELCOME_MESSAGE }]);
      setCurrentOptions(INITIAL_OPTIONS);
    }
  };

  // Close chat panel
  const handleClose = () => {
    setIsOpen(false);
  };

  // Handle quick reply click
  const handleQuickReply = (question) => {
    const entry = KNOWLEDGE_BASE[question];
    if (!entry) return;

    // Add user message
    setMessages((prev) => [...prev, { role: 'user', text: question }]);
    setCurrentOptions([]);
    setIsTyping(true);

    // Simulate typing delay, then show bot response
    const delay = 600 + Math.random() * 600;
    setTimeout(() => {
      setIsTyping(false);
      setMessages((prev) => [...prev, { role: 'bot', text: entry.answer }]);
      setCurrentOptions(entry.followUps);
    }, delay);
  };

  return (
    <>
      {/* Chat Panel */}
      {isOpen && (
        <div className="assistant-panel" ref={panelRef}>
          {/* Header */}
          <div className="assistant-header">
            <div className="assistant-header-info">
              <h3 className="assistant-header-title">
                AI Video Summarizer
              </h3>
              <p className="assistant-header-subtitle">
                built by Moazzam and Sultan
              </p>
            </div>
            <button
              className="assistant-close-btn"
              onClick={handleClose}
              aria-label="Close assistant"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div className="assistant-messages">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`assistant-msg assistant-msg--${msg.role}`}
              >
                {msg.role === 'bot' ? renderBotText(msg.text) : msg.text}
              </div>
            ))}

            {/* Typing indicator */}
            {isTyping && (
              <div className="assistant-typing">
                <div className="assistant-typing-dot" />
                <div className="assistant-typing-dot" />
                <div className="assistant-typing-dot" />
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Quick Replies */}
          {currentOptions.length > 0 && !isTyping && (
            <div className="assistant-replies">
              {currentOptions.map((option) => (
                <button
                  key={option}
                  className="assistant-reply-btn"
                  onClick={() => handleQuickReply(option)}
                >
                  {option}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Floating Action Button */}
      <div
        className="assistant-fab"
        onClick={isOpen ? handleClose : handleOpen}
      >
        <div className={`assistant-fab-btn ${!isOpen ? 'assistant-fab-btn--breathing' : ''}`}>
          {/* Notification dot — only before first open */}
          {!hasOpened && <div className="assistant-notification-dot" />}

          {/* Orbiting spark — only when closed */}
          {!isOpen && <div className="assistant-orbit-spark" />}

          {isOpen ? (
            /* Close icon when open */
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          ) : (
            /* Play + spark icon */
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z"
                    fill="white" opacity="0.95" />
              <path d="M19 2l.5 1.5L21 4l-1.5.5L19 6l-.5-1.5L17 4l1.5-.5L19 2z"
                    fill="white" opacity="0.8" />
            </svg>
          )}
        </div>
      </div>
    </>
  );
};

export default AssistantWidget;
