# CHAPTER 8: USER MANUAL

This chapter walks through every feature of VidFusion from the point of view of an end user. All screenshots were captured from a running instance of the system (FastAPI backend serving the React build on a single port, MongoDB, local BART and BGE models) on 20 October 2026, using a demonstration account. The fusion example in Sections 8.6 to 8.8 is a real job: two YouTube videos totalling 22 minutes 25 seconds were fused into a 4 minute 53 second highlight video against a 5-minute target, with about 7 minutes of processing on a CPU-only machine.

---

## 8.1 Sign Up / Login

1. Open the VidFusion landing page. It introduces the platform and its main actions: **Start Summarizing** and **View Transcripts**.

   ![Figure 8.1a: Landing page (hero section)](01_landing_page_a.png)
   *Figure 8.1a: Landing page (hero section)*

   ![Figure 8.1b: Landing page (feature sections)](01_landing_page_b.png)
   *Figure 8.1b: Landing page (feature sections)*

   ![Figure 8.1c: Landing page (footer)](01_landing_page_c.png)
   *Figure 8.1c: Landing page (footer)*

2. Click **Sign Up**. Enter your full name (optional), email address and a password, then click **Create Account**.

   ![Figure 8.2: Sign-up page](02_signup_page.png)
   *Figure 8.2: Sign-up page*

3. To sign in later, open **Log in** and enter your email or username and password, then click **Sign in**.

   ![Figure 8.3: Login page](03_login_page.png)
   *Figure 8.3: Login page*

4. If you forget your password, click **Forgot password?**, enter your registered email and click **Send Verification Code**. Enter the code you receive to set a new password.

   ![Figure 8.4: Forgot-password page](04_forgot_password.png)
   *Figure 8.4: Forgot-password page*

---

## 8.2 Search Videos by Title or Topic

1. After signing in you land on **Search & Summarize**. Type a topic or video title, or click one of the **Popular Searches**. You can optionally restrict results to Creative Commons (CC BY) videos with the license filter.

   ![Figure 8.5: Search page](05_search_page.png)
   *Figure 8.5: Search page*

2. Click **Search**. VidFusion shows matching YouTube videos as cards. Each card shows the title, channel, a license badge and three actions: **Add to Merge**, **Watch** and **YouTube**.

   ![Figure 8.6: Search results](06_search_results.png)
   *Figure 8.6: Search results*

---

## 8.3 Search Inside Transcripts (Deep Search)

1. Click **Search inside transcripts** (or open it from the navigation). The page explains when to use a keyword search instead of a title search and offers example terms. Enter a technical term such as "gradient descent" and press **Enter**.

   ![Figure 8.7: Transcript search page with a keyword entered](07_transcript_search_page.png)
   *Figure 8.7: Transcript search page with a keyword entered*

2. VidFusion searches YouTube for the topic and then scans the transcripts of the top results. Each result card shows the video, its channel, how many times the term is spoken (for example, "31 matches"), and the exact timestamps with the surrounding sentence.

   ![Figure 8.8a: Transcript search results with timestamped matches](08_transcript_search_results_a.png)
   *Figure 8.8a: Transcript search results with timestamped matches*

3. Scroll down for more matching videos. Each card can be added to a fusion with **Add to Merge**, played with **Watch**, or opened on **YouTube**.

   ![Figure 8.8b: More matching videos](08_transcript_search_results_b.png)
   *Figure 8.8b: More matching videos with their timestamped matches*

---

## 8.4 Discover Videos by Category

1. Open **Discover**. Pick a category (Technology, Health, Business, Education, Science and so on) or type a custom topic.

   ![Figure 8.9: Discover page](09_discover_page.png)
   *Figure 8.9: Discover page*

2. VidFusion fetches relevant videos for that category. Select the ones you want, and they can be summarized in the same way as search results.

   ![Figure 8.10a: Discover results for "Technology"](10_discover_topic_results_a.png)
   *Figure 8.10a: Discover results for "Technology"*

   ![Figure 8.10b: Discover results (continued)](10_discover_topic_results_b.png)
   *Figure 8.10b: Discover results (continued)*

---

## 8.5 Watch a Video and View its Transcript

1. Click **Watch** on any card to play the video inside VidFusion. Related videos appear under **More on this Topic**.

   ![Figure 8.11a: In-app video player](11_video_player_a.png)
   *Figure 8.11a: In-app video player*

   ![Figure 8.11b: Related videos](11_video_player_b.png)
   *Figure 8.11b: Related videos under the player*

2. Open **Transcripts**, paste a YouTube video ID or URL, and click **Fetch Transcript**. The timestamped transcript is shown, and you can **Copy** it or **Download** it with or without timestamps.

   ![Figure 8.12: Transcript viewer](12_transcript_viewer.png)
   *Figure 8.12: Transcript viewer*

---

## 8.6 Create a Video Fusion (Select Videos and Duration)

1. Click **Add to Merge** on one or more videos (up to five). A selection tray appears at the bottom of the screen showing the number of selected videos, their combined source length and thumbnails.

   ![Figure 8.13: Two videos selected for fusion](13_videos_selected_for_fusion.png)
   *Figure 8.13: Two videos selected for fusion (combined source length 22m 25s)*

2. Open the duration menu in the tray and choose an output length: **5 min Quick Highlights**, **10 min Key Concepts**, **15 min Balanced Summary**, **20 min Detailed Summary** or **30 min Comprehensive Summary**. Durations longer than the source are disabled, since a summary must be shorter than the source. The estimated output word count is shown below.

   ![Figure 8.14: Output duration options](14_output_duration_options.png)
   *Figure 8.14: Output duration options*

3. Click **Merge N Videos**. The job is created and you are taken to the processing page.

---

## 8.7 Monitor Processing Progress

The processing page updates automatically. A progress ring shows the percentage and the current stage message. The pipeline steps are **Transcribing**, **Analyzing**, **Selecting**, **Video Gen** and **Video Ready**, followed by **Summarizing**, **AI Enriching** and **Voice Gen** for the text summary.

1. **Transcribing**: VidFusion checks YouTube captions for each source and falls back to Whisper transcription if none are available.

   ![Figure 8.15: Transcribing stage](15_processing_transcribing.png)
   *Figure 8.15: Transcribing stage (10%)*

2. **Analyzing**: transcripts are split into semantic segments (complete thoughts) using sentence-embedding similarity.

   ![Figure 8.16: Building semantic segments](16_processing_semantic_segments.png)
   *Figure 8.16: Building semantic segments (60%)*

3. **Video Gen**: the source videos are downloaded so the selected clips can be cut.

   ![Figure 8.17: Downloading source videos](17_processing_downloading_sources.png)
   *Figure 8.17: Downloading source videos*

4. **Selecting**: the transcript of the selected segments is reconstructed for summarization.

   ![Figure 8.18: Reconstructing transcript from selected segments](18_processing_selecting_segments.png)
   *Figure 8.18: Reconstructing transcript from selected segments (84%)*

5. **Summarizing**: BART-large-CNN runs hierarchical summarization on the selected content.

   ![Figure 8.19: BART hierarchical summarization](19_processing_bart_summarization.png)
   *Figure 8.19: BART hierarchical summarization (86%)*

6. When the highlight video is assembled it becomes playable immediately, while the AI summary is still being generated.

   ![Figure 8.20: Highlight video ready](20_highlight_video_ready.png)
   *Figure 8.20: Highlight video ready, AI summary still generating*

---

## 8.8 View the Fusion Result

1. When processing finishes, the page reads **Your summary is ready**. Summary cards show the number of topics found, the percentage of source text retained, the output word count and the number of videos merged. In this run the optional quality check timed out at its 90-second limit and is reported as unavailable rather than hidden.

   ![Figure 8.21: Result overview](21_result_summary_ready.png)
   *Figure 8.21: Result overview (10 topics, 4% text retained, 148 words, 2 videos merged)*

2. **Video Highlights** plays the fused highlight video, built from clips of both source videos in the original speakers' voices. It is marked "Private Preview Only" because reuse rights for the sources are not verified.

   ![Figure 8.22: Fused highlight video](22_fused_highlight_video.png)
   *Figure 8.22: Fused highlight video (4:53 output for a 5-minute target)*

3. Scroll down to read the **TL;DR** and the full **AI Summary**.

   ![Figure 8.23: TL;DR and AI summary](23_tldr_and_ai_summary.png)
   *Figure 8.23: TL;DR and AI summary*

4. **Key Events** lists the most important points, and **Chapters** groups the summary into titled sections.

   ![Figure 8.24: Key events and chapters](24_key_events_and_chapters.png)
   *Figure 8.24: Key events and chapters*

5. **Key Topics** shows the extracted concepts. Use **Copy Text**, **Download TXT** or **Download PDF** to export the summary, or **Create Another Summary** to start again.

   ![Figure 8.25: Key topics and export options](25_key_topics_and_export.png)
   *Figure 8.25: Key topics and export options*

6. **Rights & Publication Guidance** explains each source's license status and why public publication is restricted. Click **Details** to see the per-source policy notes.

   ![Figure 8.26: Rights and publication details](26_rights_publication_details.png)
   *Figure 8.26: Rights and publication details*

7. The downloaded PDF contains the TL;DR, summary, key events and chapters.

   ![Figure 8.27: Exported PDF report](27_exported_pdf_report.png)
   *Figure 8.27: Exported PDF report (first page)*

---

## 8.9 Manage Your Account

1. Open the profile menu and choose **Account Info** to edit your first name, last name, username and email. The **Danger Zone** lets you permanently delete your account.

   ![Figure 8.28a: Account information](28_account_info_a.png)
   *Figure 8.28a: Account information*

   ![Figure 8.28b: Account deletion (danger zone)](28_account_info_b.png)
   *Figure 8.28b: Account deletion (danger zone)*

2. **Security** lets you change your password, or reset it by email if you have forgotten it.

   ![Figure 8.29a: Change password](29_security_settings_a.png)
   *Figure 8.29a: Change password*

   ![Figure 8.29b: Reset via email](29_security_settings_b.png)
   *Figure 8.29b: Reset via email*

3. **History** lists your summaries, searches, watched videos and viewed transcripts. Filter by type with the tabs, delete single entries, or use **Clear All**.

   ![Figure 8.30a: Activity history](30_activity_history_a.png)
   *Figure 8.30a: Activity history*

   ![Figure 8.30b: Activity history (continued)](30_activity_history_b.png)
   *Figure 8.30b: Activity history (continued)*

---

## 8.10 Use the Help Assistant

1. Click the floating play button in the bottom-right corner on any page to open the VidFusion assistant.

   ![Figure 8.31a: Help assistant](31_assistant_widget_a.png)
   *Figure 8.31a: Help assistant*

2. Choose a suggested question (for example "What does VidFusion do?") to get an answer with follow-up questions.

   ![Figure 8.31b: Assistant answer](31_assistant_widget_b.png)
   *Figure 8.31b: Assistant answer with follow-up questions*

---

## 8.11 About and Contact

1. **About** describes the platform's features: Smart Search, Deep Transcript Analysis, AI-Powered Summaries, Multi-Video Fusion and Privacy-First history.

   ![Figure 8.32a: About page](32_about_page_a.png)
   *Figure 8.32a: About page*

   ![Figure 8.32b: About page (continued)](32_about_page_b.png)
   *Figure 8.32b: About page (continued)*

2. **Contact** provides a form for questions and feedback.

   ![Figure 8.33a: Contact page](33_contact_page_a.png)
   *Figure 8.33a: Contact page*

   ![Figure 8.33b: Contact form](33_contact_page_b.png)
   *Figure 8.33b: Contact form*

---

## 8.12 Administrator Panel

Administrator accounts have extra pages in the profile sidebar.

1. **Platform Stats** shows user counts (total, active, inactive, active today, new this week, admins) and platform activity (total actions, searches, videos watched, merges done, transcripts viewed). Individual users' activity is not visible to admins.

   ![Figure 8.34a: Platform statistics](34_admin_dashboard_stats_a.png)
   *Figure 8.34a: Platform statistics*

   ![Figure 8.34b: Platform activity](34_admin_dashboard_stats_b.png)
   *Figure 8.34b: Platform activity*

2. **Manage Users** lets an admin search, edit, deactivate or delete users and add new ones with **Add New User**.

   ![Figure 8.35: User management](35_admin_user_management.png)
   *Figure 8.35: User management*

3. Admins also have their own **History** and **Account Info** pages.

   ![Figure 8.36a: Admin history](36_admin_activity_history_a.png)
   *Figure 8.36a: Admin history*

   ![Figure 8.36b: Admin history (continued)](36_admin_activity_history_b.png)
   *Figure 8.36b: Admin history (continued)*

   ![Figure 8.37: Admin account information](37_admin_account_info.png)
   *Figure 8.37: Admin account information*
