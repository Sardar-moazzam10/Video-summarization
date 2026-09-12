const fs = require('fs');
const file = 'src/MergedPodcastPlayer.test.js';
let content = fs.readFileSync(file, 'utf8');

// Find where "await screen.findByText('Video Highlights');" orphaned line is and delete it
content = content.replace(/await screen\.findByText\('Video Highlights'\);\s*\/\/.*/g, '');
content = content.replace(/\/\/ We expect the Video Gen step to be marked as complete even though the backend is in summarizing\./g, '');
content = content.replace(/\/\/ The component renders "Video Gen" in the STAGES map\./g, '');

fs.writeFileSync(file, content);
console.log("Cleaned up orphaned lines");
