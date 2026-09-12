from backend.services.duration_profiles import get_profile
from backend.services.summarization_policy import decide

profile = get_profile(10)
print("target_words:", profile.target_words)
# dummy text of 684 words
text = "word " * 684
decision = decide(text, target_words=profile.target_words)
print("decision:", decision.action)
