import re

with open('/home/weiblocks/Desktop/Video-summarization/backend/api/merge.py', 'r') as f:
    content = f.read()

# 1. Insert video_error = False before if job.generate_video:
content = content.replace(
    "        if job.generate_video:",
    "        video_error = False\n        if job.generate_video:"
)

# 2. Replace job_warning in video selection with video_error
content = content.replace(
    """                else:
                    job_warning = "Video generation skipped because no highlight segments were identified."
                    print(f"[Video] {job_warning}")

            except Exception as e:
                job_warning = f"Video selection failed: {e}"
                print(f"[WARN] {job_warning}")
                import traceback
                traceback.print_exc()

        if job.generate_video and highlight_segments_result and not job_warning:""",
    """                else:
                    video_error = True
                    w_msg = "Video generation skipped because no highlight segments were identified."
                    job_warning = (job_warning + " | " + w_msg) if job_warning else w_msg
                    print(f"[Video] {w_msg}")

            except Exception as e:
                video_error = True
                w_msg = f"Video selection failed: {e}"
                job_warning = (job_warning + " | " + w_msg) if job_warning else w_msg
                print(f"[WARN] {w_msg}")
                import traceback
                traceback.print_exc()

        if job.generate_video and highlight_segments_result and not video_error:"""
)

with open('/home/weiblocks/Desktop/Video-summarization/backend/api/merge.py', 'w') as f:
    f.write(content)
print("Patched merge.py")
