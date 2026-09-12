"""
Tests for grounding_check — the post-generation check that catches
ungrounded/hallucinated BART output the lexical degeneration guard in
summarization_service.py cannot see (see grounding_check.py's module
docstring for the full anchor-case trace).

REAL_SOURCE_NARRATIVE below is the exact fusion narrative from the real
job (video YIszsqhLGIs, 20-min COMPREHENSIVE profile) that produced a
summary drifting into DailyMail-style navigation boilerplate. The
GOOD/BAD sentence fixtures are copied verbatim from that real corrupted
output — the clean prefix and the hallucinated tail respectively — not
synthetic examples, so this test suite validates against the actual
failure it was written for.

These tests load the real SBERT embedder (BAAI/bge-base-en-v1.5, the
same singleton fusion_engine/vector_store already keep warm) rather than
mocking it — that's the point: a mocked embedder can't tell us whether
the real similarity signal actually separates real hallucination from
real grounded content.
"""

from backend.services.grounding_check import (
    check_grounding,
    MAX_UNSUPPORTED_FRACTION,
    MIN_CONSECUTIVE_UNSUPPORTED,
    SENTENCE_GROUNDING_THRESHOLD,
)

REAL_SOURCE_NARRATIVE = (
    "Right? So what you will see trust will start happening in multiple categories. "
    "Right? Now you've seen celebrities who've done protein have doing well, very well "
    "actually >> and you would say but that's not how trust works. Trust often works "
    "basis this for example let's say if I recommended a book right now >> it'll be "
    "bought >> yeah they trust you >> trust so there is something that trust comes in "
    "very unique ways but for example I give some kind of a workout routine you may not "
    "trust although it's not that I will not know about. >> When you fail in public >> "
    "okay >> and that probably is something that we need to because I was reading bunch "
    "of your tweets >> that is something that we need to get over in order to try more "
    "or maybe succeed as a society in a better way. >> Right? >> How do you think that "
    "will happen first? Actually why do you think failure is seen as a shameful event "
    "in our country? See the thing is the uh first of all let's just understand how we "
    "are raised.. Uh there is this perpetual fear. Everybody is living in some version "
    "of fear. Society fear exam fear and and we also raise kids through fear. Okay, if "
    "you do not do this, this will happen. Nobody will respect you. All of that stuff, "
    "right?. So when your default state is fear, failure is the dreaded, right? Uh and "
    "that causes the society to feel safe in some ways, right? But it makes it is very "
    "common in the emotional societies. For example, India was completely apathy or "
    "complete panic.. >> Right? You will notice one more thing that Indians when they "
    "rate an app they will do one star or five star two three four star right because "
    "that's an emotional response. YouTube used to be have earlier different ratings if "
    "you remember then it moved to up thumbs up and thumbs down. Yeah, >> right. "
    "Additionally, >> I had a feeling that all the countries that had extreme weather "
    "became great at planning and people who do not have extreme weather are not good "
    "at planning because extreme weather forces you to have long-term thinking, right? "
    "countries. Then I noticed that it those countries also have a very unique trait of "
    "not wearing wide range of colors. So people with extreme countries, extreme "
    "weather do not have very colorful color palette in their clothes. So when you go "
    "to countries let's say Russia you will see like only six shades but if you go to "
    "a. place in Gujarat vibrant colors in their shirts and and then I I noticed that uh "
    "further that they are also le less likely to be emotionally expressive >> "
    "countries with extreme weather >> extreme weather and people who have less colors. "
    "Furthermore, But you have to be crafty about it. You can't just like oh my "
    "message. >> Then you will get blocked. >> Yeah. For example, I say let's talk "
    "about dating scenario. What does this person want in their life? For example, "
    "let's say I'm reaching out to an investor. email pitch if you do not take any "
    "effort to find out what kind of stuff this person is likely to react to homework "
    "zero but everything else so I'll just do >> same thing in dating if you do not "
    "know what this person is expecting >> randomly you'll. text >> so you will just "
    "say hello hi hello hello hi doesn't Moreover, >> are going to be somebody who are "
    "extraordinary at keeping secrets. In related terms, it but you will say simple >> "
    "so How do you trust like who are the trustworthy individuals and who are not? "
    "Building on this, why I said that and you buy that. Another key point is that the "
    "quote tweet is saying that you make an opinion about something people will want to "
    "bash you because like it's this identity driven thing, right? It's also worth "
    "noting that definition of alpha male? >> I don't think there is I I think to me "
    "these are uh uh uh more biology definitions uh versus uh a human definitions uh in "
    "in biology is very simple that somebody who has more success to get resources or "
    "mating success is known to be alpha >> right >> but human life doesn't work that way."
)

# Verbatim from the real corrupted summary_text (job e6b2dd65, YIszsqhLGIs) — the
# genuinely grounded prefix BART produced before it started drifting.
REAL_GOOD_SUMMARY = (
    "Why do you think failure is seen as a shameful event in our country? "
    "I had a feeling that all the countries that had extreme weather became great at "
    "planning and people who do not have extreme weather are not good at planning "
    "because extreme weather forces you to have long-term thinking, right? "
    "You will notice one more thing that Indians when they rate an app they will do "
    "one star or five star two three four star right because that's an emotional "
    "response. The quote tweet is saying that you make an opinion about something "
    "people will want to bash you because like it's this identity driven thing, right?"
)

# Verbatim from the real corrupted summary_text — the hallucinated tail that
# reached production. This is THE anchor case grounding_check.py exists for.
REAL_HALLUCINATED_TAIL = (
    "Back to Mail Online home. Back to the page you go back to your page you're going "
    "back to check your email. Check your email address. Share your comments. Back "
    "into the page where you’re back to the front page. Please share your page. "
    "Back to the page.back to the back page.Back to the story. Back page. Tell your "
    "email report. Send it to the comment. Back door. Contact us. Back through the "
    "page[to thepage.tomtom.tom.com/tomtom . Back page . Back "
    "tkom.tomahrahn.tomarhin.tomam.tomai.toman.tomahn.com.tomarnarn.tomohrahn@"
    "tomahnow.tomany.tomnapp.tomann.tomanker.tomall@tomasker.uk.tomlin.com . "
    "Backdoor.tomlahn.joker.tomor.tomin.tom ."
)

# The exact real corrupted output, prefix + tail together — what actually shipped.
REAL_CORRUPTED_SUMMARY = REAL_GOOD_SUMMARY + " " + REAL_HALLUCINATED_TAIL

# A genuine, non-verbatim abstraction of the source (not copy-pasted from it) —
# checks the threshold doesn't just do substring matching.
REAL_PARAPHRASE_SUMMARY = (
    "People often see failure as embarrassing in this culture, which makes it harder "
    "to take risks. Countries with harsher climates tend to plan further ahead, and "
    "the same emotional, all-or-nothing instinct shows up in how people rate apps and "
    "react to opinions online."
)


class TestGroundingCheckCalibration:
    """Item 5/6/7: the exact real bug must fail; real good/paraphrased text must pass."""

    def test_exact_real_corrupted_output_fails_grounding(self):
        result = check_grounding(REAL_CORRUPTED_SUMMARY, REAL_SOURCE_NARRATIVE)
        assert not result.is_grounded
        assert result.reasons
        assert result.unsupported_fraction > MAX_UNSUPPORTED_FRACTION
        assert result.longest_unsupported_run >= MIN_CONSECUTIVE_UNSUPPORTED

    def test_real_good_grounded_summary_passes(self):
        result = check_grounding(REAL_GOOD_SUMMARY, REAL_SOURCE_NARRATIVE)
        assert result.is_grounded
        assert result.reasons == []

    def test_real_paraphrased_summary_passes(self):
        """A genuine abstraction (not verbatim) must not be mistaken for hallucination."""
        result = check_grounding(REAL_PARAPHRASE_SUMMARY, REAL_SOURCE_NARRATIVE)
        assert result.is_grounded

    def test_hallucinated_tail_alone_fails(self):
        """Isolate just the bad half — should fail on its own, not only in combination."""
        result = check_grounding(REAL_HALLUCINATED_TAIL, REAL_SOURCE_NARRATIVE)
        assert not result.is_grounded


class TestGroundingPatternChecks:
    """Denylist/regex layer is a supporting signal, not the sole mechanism."""

    def test_domain_like_garbage_is_flagged_regardless_of_similarity(self):
        result = check_grounding(REAL_HALLUCINATED_TAIL, REAL_SOURCE_NARRATIVE)
        assert any("domain-like" in r for r in result.reasons)

    def test_short_output_is_not_semantically_judged(self):
        """Below MIN_SENTENCES_FOR_GROUNDING_CHECK, similarity is too noisy — skip it."""
        result = check_grounding("A short summary.", REAL_SOURCE_NARRATIVE)
        assert result.is_grounded

    def test_clean_short_output_with_no_patterns_is_not_flagged(self):
        result = check_grounding("Failure is often seen as shameful.", "Failure is shameful in many places.")
        assert result.is_grounded
