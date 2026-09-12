import { nextVisitedStages, getStepStatus, PIPELINE_STAGES } from '../src/utils/progressState.js';
let visited = new Set();
visited = nextVisitedStages(visited, 'summarizing');
console.log('visited:', Array.from(visited));
console.log('generating_video status:', getStepStatus('generating_video', 'summarizing', visited));
console.log('summarizing status:', getStepStatus('summarizing', 'summarizing', visited));
console.log('video_ready status:', getStepStatus('video_ready', 'summarizing', visited));
