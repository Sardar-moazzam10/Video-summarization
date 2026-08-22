import React, { useState, useRef, useEffect } from 'react';

import './AssistantWidget.css';

// =====================================================
// KNOWLEDGE BASE — full, accurate, no Gemini references
// =====================================================

const INITIAL_OPTIONS = [
  "What does VidFusion do?",
  "How do I get started?",
  "What output durations are available?",
  "How does the processing work?",
];

const KNOWLEDGE_BASE = {

  // ── OVERVIEW ──────────────────────────────────────
  "What does VidFusion do?": {
    answer:
      "VidFusion turns long YouTube videos into short, intelligent summaries. You pick 1–10 YouTube videos, choose how long you want the output (5, 10, 15, or 20 minutes), and VidFusion produces:\n\n• A written summary with TLDR, chapters, and key takeaways\n• An MP3 of the summary in the original speakers' voices\n• A highlight video reel using clips from the original videos\n• An AI chat so you can ask questions about the content\n• Downloadable PDF, text, and subtitle files",
    followUps: [
      "How do I get started?",
      "What output durations are available?",
      "What features are on the results page?",
    ],
  },

  // ── GETTING STARTED ───────────────────────────────
  "How do I get started?": {
    answer:
      "Here is the step-by-step new user flow:\n\n**1. Create an account** → go to /signup, fill in name, email, username, password\n**2. Verify your email** → check inbox for the 6-digit code → enter it at /verify-code\n**3. Log in** → /login → you land on the Search page\n**4. Find videos** → use Search (type a title) or Discover (pick a topic)\n**5. Select 1–10 videos** → click any video card to select it\n**6. Choose output duration** → 5, 10, 15, or 20 minutes\n**7. Click Summarize** → processing begins automatically\n**8. Get results** → video, audio, summary, chapters, chat all appear when done",
    followUps: [
      "How do I find videos?",
      "What output durations are available?",
      "How does the processing work?",
    ],
  },

  // ── FINDING VIDEOS ────────────────────────────────
  "How do I find videos?": {
    answer:
      "There are two ways to find YouTube videos on VidFusion:\n\n**Search (Navbar → Search)**\nType any YouTube search query — e.g. \"Lex Fridman podcast AI\" — and results appear as cards. Click any card to select it.\n\n**Discover (Navbar → Discover)**\nChoose from topic pills: Technology, Health, Business, Sports, Science, Gaming, Motivation, and more. VidFusion fetches the top YouTube videos for that topic automatically.\n\nBoth paths lead to the same selection flow: pick 1–10 videos, choose duration, click Summarize.",
    followUps: [
      "What output durations are available?",
      "When should I select multiple videos?",
      "How does the processing work?",
    ],
  },

  "When should I select multiple videos?": {
    answer:
      "Select multiple videos when:\n\n• You found 3–4 podcasts on the same topic and want **one unified summary** instead of watching all of them\n• You want to **compare two speakers' perspectives** — the fusion engine merges and deduplicates their content\n• A series has multiple parts — summarize all parts together\n• You want a **topic overview** from several sources at once\n\nVidFusion can handle up to 10 videos at once. The fusion engine identifies overlapping topics and builds a single coherent narrative.",
    followUps: [
      "What output durations are available?",
      "How does the processing work?",
      "What features are on the results page?",
    ],
  },

  // ── OUTPUT DURATIONS ──────────────────────────────
  "What output durations are available?": {
    answer:
      "You can choose one of four output lengths:\n\n**Quick Scan — 5 min (~10 clips)**\nBest for: short videos under 30 min, or when you only need key highlights\n\n**Brief Summary — 10 min (~20 clips)**\nBest for: everyday use — good balance of depth and speed\n\n**Full Coverage — 15 min (~30 clips)**\nBest for: lectures, documentaries, complex videos 30–90 min long\n\n**Deep Dive — 20 min (~40 clips)**\nBest for: 2h+ podcasts, conference talks, multi-part series\n\nYour chosen length is the length of the highlight reel and its audio.",
    followUps: [
      "How does the processing work?",
      "What features are on the results page?",
      "How does the highlight video work?",
    ],
  },

  // ── PROCESSING STAGES ─────────────────────────────
  "How does the processing work?": {
    answer:
      "After clicking Summarize, VidFusion runs 7 stages automatically:\n\n**01 Transcribing** — fetches spoken words from each video (YouTube API → yt-dlp → Whisper AI fallback)\n**02 Analyzing** — detects topics, language, structure. Non-English? NLLB-200 translates to English\n**03 Fusing** — merges content from all selected videos, removes duplicates\n**04 Summarizing** — BART-large-CNN compresses the narrative to your target word count\n**05 AI Enriching** — Ollama LLM adds chapters, TLDR, key takeaways\n**06 Selecting** — SBERT + TF-IDF rank transcript segments against the summary\n**07 Video Gen** — top clips trimmed from the original videos → concatenated, original audio kept\n\nProgress is shown live on the page.",
    followUps: [
      "How long does processing take?",
      "What features are on the results page?",
      "How does the highlight video work?",
    ],
  },

  "How long does processing take?": {
    answer:
      "Typical processing times:\n\n• 1 video, 5-min output → **3–5 minutes**\n• 2 videos, 10-min output → **6–10 minutes**\n• 3+ videos, 20-min output → **12–18 minutes**\n\nLonger videos (2h+) or non-English videos (need NLLB translation) take more time. You can leave the page and come back — the job keeps running in the background.",
    followUps: [
      "What features are on the results page?",
      "How does the highlight video work?",
      "Can I chat with the video?",
    ],
  },

  // ── RESULTS PAGE ──────────────────────────────────
  "What features are on the results page?": {
    answer:
      "When processing completes, the same page transforms into a results dashboard with:\n\n**A — Highlight Video** — clips from the original videos, played in narration order with original speaker audio\n**B — Audio** — standalone MP3 player with the highlight reel's original audio\n**C — Text Summary** — full written summary with paragraphs\n**D — TLDR + Chapters + Takeaways** — 2-sentence core point, 5 key bullet points, 3 chapter sections\n**E — AI Chat** — type any question about the video content\n**F — Downloads** — audio MP3, text export, PDF with chapters, SRT subtitles\n**G — Warning banner** — if video highlights failed, you still get everything else",
    followUps: [
      "How does the highlight video work?",
      "Can I chat with the video?",
      "What can I download?",
    ],
  },

  // ── HIGHLIGHT VIDEO ───────────────────────────────
  "How does the highlight video work?": {
    answer:
      "The highlight video is built in 4 steps:\n\n**1. Score-based clip selection** — every transcript segment is ranked against the summary using SBERT (Sentence-BERT) and TF-IDF. The highest-scoring segments become clips.\n\n**2. Precise trimming** — FFmpeg cuts each clip using two-stage seeking: fast keyframe seek + precise sub-second offset. Clips start at the exact timestamp, not at a keyframe boundary.\n\n**3. Original audio throughout** — the video and the MP3 both use the original speakers' voices. Natural pauses within a clip are preserved. Between clips, a 0.4-second black frame signals a topic change.\n\n**4. Audio fade** — each clip has a 0.3s fade in/out so transitions feel smooth.",
    followUps: [
      "Can I chat with the video?",
      "What can I download?",
      "What AI models are used?",
    ],
  },

  // ── AI CHAT ───────────────────────────────────────
  "Can I chat with the video?": {
    answer:
      "Yes! The results page has a **Chat with Video** section at the bottom.\n\nHow it works:\n• You type any question — e.g. \"What did the speaker say about inflation?\"\n• FAISS semantic search finds the most relevant transcript segments\n• Ollama LLM (local, free) synthesizes a concise answer grounded in the actual video content\n• Answers are never hallucinated — they come from what was actually said in the video\n\nYou can ask anything: topic explanations, quotes, chapter summaries, comparisons between speakers.",
    followUps: [
      "What AI models are used?",
      "What can I download?",
      "How do I view the raw transcript?",
    ],
  },

  // ── DOWNLOADS ─────────────────────────────────────
  "What can I download?": {
    answer:
      "From the results page you can download:\n\n• **Audio MP3** — the highlight audio in the original speakers' voices\n• **Text file (.txt)** — plain text summary\n• **PDF** — formatted document with TLDR, chapters, and key takeaways\n\nAll downloads are generated automatically — nothing extra to configure.",
    followUps: [
      "How do I view the raw transcript?",
      "What is in my account history?",
      "What does VidFusion do?",
    ],
  },

  // ── TRANSCRIPT VIEWER ─────────────────────────────
  "How do I view the raw transcript?": {
    answer:
      "Go to **Navbar → Transcripts** (or directly to /transcript-viewer).\n\nYou'll see the word-for-word transcript of any YouTube video with timestamps. Use this when:\n• You want to read the original content yourself\n• You want to find the exact quote and timestamp\n• You want to verify the summary is accurate\n\nYou can also go to /transcript-viewer/{videoId} to jump directly to a specific video's transcript.",
    followUps: [
      "What is in my account history?",
      "How do I manage my account?",
      "Can I chat with the video?",
    ],
  },

  // ── USER PANEL ────────────────────────────────────
  "What is in my account history?": {
    answer:
      "Your history page (/history) tracks everything you do on VidFusion:\n\n• **Summaries** — every merge/summarization job you ran (click to reopen results)\n• **Searches** — every query you typed in the Search page\n• **Watched** — videos you opened in the video player\n• **Transcripts** — transcripts you viewed\n\nAll entries are clickable — summaries reopen the results, searches re-run the query. You can also clear your history from this page.",
    followUps: [
      "How do I manage my account?",
      "How do I change my password?",
      "What does VidFusion do?",
    ],
  },

  "How do I manage my account?": {
    answer:
      "Click your **username in the top-right navbar → Manage Account**. You have three pages:\n\n**Account Info (/account-info)**\n• View and update your name and email\n• See your account creation date\n\n**Security (/security)**\n• Change your password (requires current password to confirm)\n\n**History (/history)**\n• All your searches, summaries, watched videos, and transcript views\n• Filter by type; click any entry to revisit it",
    followUps: [
      "How do I change my password?",
      "What is in my account history?",
      "How do I get started?",
    ],
  },

  "How do I change my password?": {
    answer:
      "Go to **Navbar → your username → Manage Account → Security** (or /security directly).\n\nEnter your current password, then your new password twice. Click Save. If you forgot your password, use the **Forgot Password** link on the login page:\n\n/forgot-password → enter email → receive 6-digit code → /verify-code → /reset-password → done.",
    followUps: [
      "How do I manage my account?",
      "How do I get started?",
      "What does VidFusion do?",
    ],
  },

  // ── AI MODELS ─────────────────────────────────────
  "What AI models are used?": {
    answer:
      "VidFusion uses these AI models — all free, all running locally:\n\n**BART-large-CNN** — hierarchical text summarization (compresses transcripts to target word count)\n**Sentence-BERT (all-MiniLM-L6-v2)** — semantic similarity for clip selection, deduplication, and AI chat search\n**FAISS** — vector index for fast semantic search across all video transcripts\n**Ollama (local LLM)** — generates chapters, TLDR, key takeaways, and answers chat questions\n**Whisper** — speech-to-text when YouTube transcripts are unavailable\n**NLLB-200** — translates non-English transcripts to English (200 languages)\n**CLIP ViT-B/16** — cross-modal visual-text scoring for selecting the most relevant video frames",
    followUps: [
      "How does the processing work?",
      "How does the highlight video work?",
      "Can I chat with the video?",
    ],
  },

  // ── TROUBLESHOOTING ───────────────────────────────
  "What if the video fails or gets stuck?": {
    answer:
      "A few common situations:\n\n**Stuck at a stage for 10+ min** — the job has a timeout system. If a stage (e.g. translation, video download) times out, it automatically falls back and continues.\n\n**'Something went wrong' banner** — the summary and audio still completed. Only the video highlight reel failed. You still have the full written summary, audio narration, TLDR, chapters, and chat.\n\n**Stuck at 98% (video generation)** — this usually means the video download timed out. Try with a shorter or different video.\n\n**Non-English video** — VidFusion auto-detects the language and translates via NLLB-200. If translation times out, it proceeds with the original text (summary quality may be reduced).",
    followUps: [
      "How long does processing take?",
      "What features are on the results page?",
      "How do I get started?",
    ],
  },
};

const WELCOME_MESSAGE =
  "Hey! I'm your VidFusion assistant. I can help you learn about every feature of the platform and guide you step by step. What would you like to know?";


// ── RENDER HELPERS ───────────────────────────────────

function renderBotText(text) {
  return text.split('\n').map((line, lineIdx) => {
    const parts = line.split(/(\*\*[^*]+\*\*)/g);
    const rendered = parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      return <span key={i}>{part}</span>;
    });
    return (
      <React.Fragment key={lineIdx}>
        {rendered}
        {lineIdx < text.split('\n').length - 1 && <br />}
      </React.Fragment>
    );
  });
}

// =====================================================
// COMPONENT
// =====================================================

const AssistantWidget = () => {
  const [isOpen, setIsOpen]          = useState(false);
  const [messages, setMessages]      = useState([]);
  const [isTyping, setIsTyping]      = useState(false);
  const [currentOptions, setOptions] = useState(INITIAL_OPTIONS);
  const [hasOpened, setHasOpened]    = useState(false);

  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isTyping]);

  const handleOpen = () => {
    setIsOpen(true);
    if (!hasOpened) {
      setHasOpened(true);
      setMessages([{ role: 'bot', text: WELCOME_MESSAGE }]);
      setOptions(INITIAL_OPTIONS);
    }
  };

  const handleClose = () => setIsOpen(false);

  const handleQuickReply = (question) => {
    const entry = KNOWLEDGE_BASE[question];
    if (!entry) return;
    setMessages(prev => [...prev, { role: 'user', text: question }]);
    setOptions([]);
    setIsTyping(true);
    const delay = 500 + Math.random() * 400;
    setTimeout(() => {
      setIsTyping(false);
      setMessages(prev => [...prev, { role: 'bot', text: entry.answer }]);
      setOptions(entry.followUps || []);
    }, delay);
  };

  return (
    <>
      {/* Chat Panel */}
      {isOpen && (
        <div className="assistant-panel">
          {/* Header */}
          <div className="assistant-header">
            <div className="assistant-header-info">
              <h3 className="assistant-header-title">VidFusion</h3>
              <p className="assistant-header-subtitle">Built by Moazzam and Sultan</p>
            </div>
            <button className="assistant-close-btn" onClick={handleClose} aria-label="Close">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div className="assistant-messages">
            {messages.map((msg, i) => (
              <div key={i} className={`assistant-msg assistant-msg--${msg.role}`}>
                {msg.role === 'bot' ? renderBotText(msg.text) : msg.text}
              </div>
            ))}
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
              {currentOptions.map(opt => (
                <button key={opt} className="assistant-reply-btn" onClick={() => handleQuickReply(opt)}>
                  {opt}
                </button>
              ))}
            </div>
          )}

        </div>
      )}

      {/* Floating Action Button */}
      <div className="assistant-fab" onClick={isOpen ? handleClose : handleOpen}>
        <div className={`assistant-fab-btn ${!isOpen ? 'assistant-fab-btn--breathing' : ''}`}>
          {!hasOpened && <div className="assistant-notification-dot" />}
          {!isOpen && <div className="assistant-orbit-spark" />}
          {isOpen ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          ) : (
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
