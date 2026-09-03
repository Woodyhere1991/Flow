r"""
Built-in New Zealand dictionary: te reo Māori words and place names.

Speech models trained mostly on American and British English mangle te reo
heard inside English sentences: whānau becomes "huanah", marae becomes
"marie", Tauranga becomes "Turnga", and macrons are dropped. This module is
the data half of the fix; hotkey.py applies it to every dictation before
the user's own personal rules, so anything a user has taught themselves
always wins over a built-in correction.

Two kinds of entry:

  EXACT_REPLACEMENTS  heard phrase -> correct form, matched
                      case-insensitively as whole words. For the
                      predictable misses: missing macrons, joined words,
                      and mangles we have actually observed.

  SOUND_WORDS         correct forms matched by pronunciation (the same
                      phonetic key used for taught personal names), for
                      mangles that cannot be listed exhaustively -
                      "Turnga" for Tauranga, "marie" for marae. Only
                      words with a distinctive key belong here: the key
                      must be unambiguous across this list.

Keep this list conservative. A wrong built-in correction is worse than a
missing one, because users never see it happen.
"""

# Joined words and observed mangles first, then macron restorations, then
# place names. Order does not matter - longest phrase is applied first.
EXACT_REPLACEMENTS = {
    # The model sometimes writes the greeting as one word.
    "kiaora": "kia ora",

    # Observed mangles of te reo words (seen in dictation testing).
    "huanah": "whānau",
    "huana": "whānau",

    # Macron restoration. "Māori" keeps its capital: NZ English writes the
    # people and the language with one, like "English".
    "maori": "Māori",
    "whanau": "whānau",
    "nga": "ngā",
    "nga mihi": "ngā mihi",
    "korero": "kōrero",
    "morena": "mōrena",
    "tena koe": "tēnā koe",
    "tena koutou": "tēnā koutou",
    "tena tatou": "tēnā tātou",
    "hapu": "hapū",
    "hangi": "hāngī",
    "powhiri": "pōwhiri",
    "wananga": "wānanga",
    "kohanga": "kōhanga",
    "turangawaewae": "tūrangawaewae",

    # Place names - capitalised, macrons where the official name has them.
    # NOT included: "taupo" -> Taupo with macron. The everyday English word
    # "top" is often heard as "taupo", and turning "top" into a place name
    # (seen in real dictation: "go over the Taupo of all the apps") is far
    # worse than an unmacroned place name.
    "whakatane": "Whakatāne",
    "whangarei": "Whangārei",
    "kaikoura": "Kaikōura",
    "opotiki": "Ōpōtiki",
    "otaki": "Ōtaki",
    "oamaru": "Ōamaru",
}

# Matched by sound, not spelling, for mangles that cannot be listed. The
# phonetic key is crude: it keeps only consonants, so an entry is only safe
# when NO common English word shares its key. Removed after real collisions:
#   marae (marry, merry)         Tauranga (turning, training)
#   Rotorua (artery)             Papamoa (pompom)
#   Whangarei (whinger)          Taupo (top)
# A wrong built-in correction is worse than a missing one - users never see
# it happen. If a new word is needed, check its consonant skeleton against
# common English words first.
SOUND_WORDS = [
    "Whakatāne",
]
