with open('tests/test_video_first_pipeline.py', 'r') as f:
    content = f.read()

patch_block = '''         patch("backend.api.merge._freeze_job_rights", side_effect=fake_freeze_rights), \\
         patch("asyncio.sleep", new_callable=AsyncMock):'''

new_patch_block = '''         patch("backend.api.merge._freeze_job_rights", side_effect=fake_freeze_rights), \\
         patch("backend.api.merge.create_shadow_job_decisions", new_callable=AsyncMock), \\
         patch("backend.api.merge.finalize_shadow_manifest", new_callable=AsyncMock), \\
         patch("backend.api.merge.append_event", new_callable=AsyncMock), \\
         patch("backend.api.merge.set_observation_context", return_value="dummy_token"), \\
         patch("backend.api.merge.reset_observation_context"), \\
         patch("backend.api.merge.load_job_decision_ids", new_callable=AsyncMock), \\
         patch("asyncio.sleep", new_callable=AsyncMock):'''

content = content.replace(patch_block, new_patch_block)

with open('tests/test_video_first_pipeline.py', 'w') as f:
    f.write(content)
