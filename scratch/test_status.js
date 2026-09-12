import { getStepStatus, nextVisitedStages } from '../src/utils/progressState.js';
let visited = new Set(['transcribing', 'analyzing', 'fusing', 'generating_video', 'video_ready']);
console.log("visited before summarizing:", Array.from(visited));
console.log("generating_video status:", getStepStatus('generating_video', 'video_ready', visited));
console.log("video_ready status:", getStepStatus('video_ready', 'video_ready', visited));
visited = nextVisitedStages(visited, 'summarizing');
console.log("visited after summarizing:", Array.from(visited));
console.log("generating_video status:", getStepStatus('generating_video', 'summarizing', visited));
console.log("video_ready status:", getStepStatus('video_ready', 'summarizing', visited));
