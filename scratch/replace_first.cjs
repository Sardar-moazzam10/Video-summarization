const fs = require('fs');
const file = 'src/MergedPodcastPlayer.js';
let content = fs.readFileSync(file, 'utf8');

content = content.replace('{STAGES.map((s, i) => {', '{STAGES.slice(0, 5).map((s, i) => {');

fs.writeFileSync(file, content);
console.log('Replaced first map');
