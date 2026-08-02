# Flow product research

Updated: 2026-08-03

## Product position

Flow's strongest point is private, local, fast Windows dictation with no account
or subscription. Keep that. Do not turn it into a complicated cloud writing app.

## What Wispr Flow does well

Current Wispr Flow materials emphasize:

- dictation into any app;
- removal of fillers, punctuation, lists, and mid-sentence corrections;
- a personal dictionary that learns corrected spellings;
- reusable spoken snippets;
- app-specific writing styles and nearby-screen context;
- undo, history, usage statistics, 100+ languages, and mobile sync.

Its current desktop onboarding tests microphone response, teaches the shortcut,
asks for language, and provides a practice dictation. The public setup guide does
not describe retraining a personal speech model from one calibration sentence.

Sources:

- https://wisprflow.ai/features
- https://docs.wisprflow.ai/articles/3152211871-setup-guide
- https://docs.wisprflow.ai/articles/5096240724-navigating-the-wispr-flow-app-desktop-ios-and-android
- https://docs.wisprflow.ai/articles/4678293671-feature-context-awareness

## What is worth building

In priority order:

1. **Personalize and voice check.** Test that the microphone and transcription
   work, then let the user teach names, emails, and uncommon phrases. Describe
   this honestly as a check, not neural-model calibration.
2. **Correct and undo.** Let the user repair the last result without fighting
   the target app, and remember spelling corrections locally.
3. **Snippets.** Expand a short spoken cue into a saved address, reply, or link.
4. **Language and microphone selection.** Remove the current hard-coded English
   and default-microphone assumptions.
5. **Optional local history.** Off by default, with a clear delete button.

Defer app-specific writing styles, screen reading, cloud accounts, team
dashboards, and mobile sync. They add substantial complexity and weaken Flow's
privacy advantage.

## Personalization approach

A single read-aloud sentence cannot meaningfully retrain CrisperWhisper. It can
verify microphone quality and reveal obvious errors. For names and rare terms,
ASR research supports contextual biasing or spelling correction. The installed
standard CrisperWhisper model does not safely support hotwords, so Flow should
use a local personal replacement list for now.

Relevant research:

- https://aclanthology.org/2024.lrec-main.262/
- https://arxiv.org/abs/2203.00888

## Commercial value and licensing

There is real demand. Wispr advertises a $15 USD/user/month Pro plan and a free
tier limited by weekly words. Its published materials say it has hundreds of
thousands of daily active users. A simpler offline Windows alternative could be
valuable to privacy-conscious users, people with accessibility needs, and users
who dislike subscriptions.

However, Flow cannot currently be sold as-is. The CrisperWhisper Python package
is MIT, but the CrisperWhisper 2.0 model weights used by Flow are under the Nyra
Health Non-Commercial Research License. Commercial use requires a licence.

Commercial paths:

1. Obtain a commercial CrisperWhisper licence from Nyra.
2. Replace the model with OpenAI Whisper/faster-whisper, whose code and weights
   are permissively licensed, then reproduce cleanup through local rules.

Sources:

- https://wisprflow.ai/business
- https://wisprflow.ai/post/the-master-plan
- https://huggingface.co/nyralabs/CrisperWhisper2.0_turbo
- https://github.com/openai/whisper

Do not charge users or advertise commercial availability until the model choice
and every bundled dependency have received a proper licence review.
