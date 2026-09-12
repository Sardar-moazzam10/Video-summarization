const fs = require('fs');
const file = 'src/MergedPodcastPlayer.js';
let content = fs.readFileSync(file, 'utf8');

// Replace the first STAGES.map (in processing card)
content = content.replace(
  /{STAGES\.map\(\(s, i\) => {/g,
  (match, offset, string) => {
    // Only replace the first one which is inside isProcessing
    if (offset < 40000 && string.slice(Math.max(0, offset - 1000), offset).includes('processingCard')) {
      return '{STAGES.slice(0, 5).map((s, i) => {';
    }
    // Replace the second one inside tldrCard (summary pending)
    if (offset > 10000 && string.slice(Math.max(0, offset - 1000), offset).includes('tldrCard')) {
      return '{STAGES.slice(5).map((s, i) => {';
    }
    return match;
  }
);

fs.writeFileSync(file, content);
console.log('Modified STAGES.map');
