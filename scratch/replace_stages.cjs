const fs = require('fs');
const file = 'src/MergedPodcastPlayer.js';
let content = fs.readFileSync(file, 'utf8');

let replacedFirst = false;
let replacedSecond = false;

content = content.replace(/{STAGES\.map\(\(s, i\) => {/g, (match, offset) => {
  const context = content.slice(Math.max(0, offset - 500), offset);
  if (context.includes('styles.processingCard') || context.includes('processingCard')) {
    replacedFirst = true;
    return '{STAGES.slice(0, 5).map((s, i) => {';
  } else if (context.includes('styles.tldrCard') || context.includes('tldrCard') || context.includes('Generating Summary')) {
    replacedSecond = true;
    return '{STAGES.slice(5).map((s, i) => {';
  }
  return match;
});

fs.writeFileSync(file, content);
console.log('replacedFirst:', replacedFirst, 'replacedSecond:', replacedSecond);
