/*
 * Interface languages.
 *
 * These strings ship inside the app, so switching language works offline.
 * There is no translation API call at runtime — during a flood there is
 * nothing to call.
 *
 * IMPORTANT: the Assamese, Bengali and Hindi strings below are a starting
 * point and MUST be checked by a native speaker before the demo. A wrong
 * word on "road passable" in a disaster app is worse than English.
 * Mark each language verified in VERIFIED below once someone has read it.
 */

export const VERIFIED = {
  en: true,
  as: false,   // <- get an Assamese speaker to read every string, then set true
  bn: false,
  hi: false,
};

export const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "as", label: "অসমীয়া" },
  { code: "bn", label: "বাংলা" },
  { code: "hi", label: "हिन्दी" },
];

export const STRINGS = {
  en: {
    subtitle: "Volunteer · field report",
    offline: "Offline — saving to this phone",
    online: "Connected — uploading as you go",
    waiting: n => `${n} waiting`,
    newReport: "New report",
    whatHappening: "What is happening",
    describePlaceholder: "Describe what you can see",
    people: "People",
    waterLevel: "Water level",
    notSure: "Not sure",
    ankle: "Ankle deep",
    knee: "Knee deep",
    waist: "Waist deep",
    above: "Above waist",
    roadPassable: "Road still passable",
    yes: "Yes",
    no: "No",
    injured: "Someone injured",
    vulnerable: "Children or elderly",
    rising: "Water rising",
    photos: "Photos",
    save: "Save report",
    savedNote: "Saved on this phone. It will upload on its own when a signal is found.",
    queueTitle: "Waiting to upload",
    queueEmpty: "Nothing waiting. Everything has reached the control room.",
    nothingWaiting: "nothing waiting",
    summary: (r, p) => `${r} reports · ${p} photos`,
    justNow: "just now",
    minAgo: n => `${n} min ago`,
    textReady: n => `Text ready · ${n} photos`,
    demoControls: "Demo controls",
    goOffline: "Simulate going offline",
    goOnline: "Simulate coming back online",
    forceSync: "Force sync now",
    unverified: "This translation has not been checked by a native speaker yet.",
  },

  as: {
    subtitle: "স্বেচ্ছাসেৱী · ক্ষেত্ৰ প্ৰতিবেদন",
    offline: "সংযোগ নাই — এই ফোনতে ৰক্ষা কৰা হৈছে",
    online: "সংযোগ আছে — পঠিওৱা হৈ আছে",
    waiting: n => `${n} টা বাকী`,
    newReport: "নতুন প্ৰতিবেদন",
    whatHappening: "কি হৈ আছে",
    describePlaceholder: "আপুনি যি দেখিছে সেয়া লিখক",
    people: "মানুহৰ সংখ্যা",
    waterLevel: "পানীৰ উচ্চতা",
    notSure: "নিশ্চিত নহয়",
    ankle: "ভৰিৰ গাঁঠিলৈ",
    knee: "আঁঠুলৈ",
    waist: "কঁকাললৈ",
    above: "কঁকালতকৈ ওপৰত",
    roadPassable: "বাট এতিয়াও যাব পৰা নে",
    yes: "হয়",
    no: "নহয়",
    injured: "কোনোবা আঘাতপ্ৰাপ্ত",
    vulnerable: "শিশু বা বৃদ্ধ আছে",
    rising: "পানী বাঢ়ি আছে",
    photos: "ফটো",
    save: "প্ৰতিবেদন ৰক্ষা কৰক",
    savedNote: "এই ফোনত ৰক্ষা কৰা হ'ল। ছিগনেল পালে নিজেই পঠিয়াব।",
    queueTitle: "পঠিয়াবলৈ বাকী",
    queueEmpty: "একো বাকী নাই। সকলো নিয়ন্ত্ৰণ কক্ষলৈ গৈছে।",
    nothingWaiting: "একো বাকী নাই",
    summary: (r, p) => `${r} প্ৰতিবেদন · ${p} ফটো`,
    justNow: "এইমাত্ৰ",
    minAgo: n => `${n} মিনিট আগতে`,
    textReady: n => `লিখা সাজু · ${n} ফটো`,
    demoControls: "ডেমো নিয়ন্ত্ৰণ",
    goOffline: "সংযোগ বন্ধ কৰা",
    goOnline: "সংযোগ ঘূৰাই অনা",
    forceSync: "এতিয়াই পঠিয়াওক",
    unverified: "এই অনুবাদ এতিয়ালৈকে স্থানীয় ভাষাভাষীয়ে পৰীক্ষা কৰা নাই।",
  },

  bn: {
    subtitle: "স্বেচ্ছাসেবক · মাঠ প্রতিবেদন",
    offline: "সংযোগ নেই — এই ফোনেই সংরক্ষিত হচ্ছে",
    online: "সংযুক্ত — পাঠানো হচ্ছে",
    waiting: n => `${n} টি বাকি`,
    newReport: "নতুন প্রতিবেদন",
    whatHappening: "কী ঘটছে",
    describePlaceholder: "আপনি যা দেখছেন লিখুন",
    people: "মানুষের সংখ্যা",
    waterLevel: "পানির উচ্চতা",
    notSure: "নিশ্চিত নই",
    ankle: "গোড়ালি পর্যন্ত",
    knee: "হাঁটু পর্যন্ত",
    waist: "কোমর পর্যন্ত",
    above: "কোমরের উপরে",
    roadPassable: "রাস্তা এখনও চলাচলযোগ্য কি",
    yes: "হ্যাঁ",
    no: "না",
    injured: "কেউ আহত",
    vulnerable: "শিশু বা বয়স্ক আছে",
    rising: "পানি বাড়ছে",
    photos: "ছবি",
    save: "প্রতিবেদন সংরক্ষণ করুন",
    savedNote: "এই ফোনে সংরক্ষিত হয়েছে। সিগন্যাল পেলে নিজেই পাঠাবে।",
    queueTitle: "পাঠানো বাকি",
    queueEmpty: "কিছু বাকি নেই। সব নিয়ন্ত্রণ কক্ষে পৌঁছেছে।",
    nothingWaiting: "কিছু বাকি নেই",
    summary: (r, p) => `${r} প্রতিবেদন · ${p} ছবি`,
    justNow: "এইমাত্র",
    minAgo: n => `${n} মিনিট আগে`,
    textReady: n => `লেখা তৈরি · ${n} ছবি`,
    demoControls: "ডেমো নিয়ন্ত্রণ",
    goOffline: "সংযোগ বন্ধ করা",
    goOnline: "সংযোগ ফিরিয়ে আনা",
    forceSync: "এখনই পাঠান",
    unverified: "এই অনুবাদ এখনও স্থানীয় ভাষাভাষী দ্বারা যাচাই করা হয়নি।",
  },

  hi: {
    subtitle: "स्वयंसेवक · क्षेत्र रिपोर्ट",
    offline: "कनेक्शन नहीं — इसी फ़ोन में सहेजा जा रहा है",
    online: "जुड़ा हुआ — भेजा जा रहा है",
    waiting: n => `${n} बाकी`,
    newReport: "नई रिपोर्ट",
    whatHappening: "क्या हो रहा है",
    describePlaceholder: "आप जो देख रहे हैं वह लिखें",
    people: "लोगों की संख्या",
    waterLevel: "पानी का स्तर",
    notSure: "पक्का नहीं",
    ankle: "टखने तक",
    knee: "घुटने तक",
    waist: "कमर तक",
    above: "कमर से ऊपर",
    roadPassable: "क्या रास्ता अब भी चलने लायक है",
    yes: "हाँ",
    no: "नहीं",
    injured: "कोई घायल है",
    vulnerable: "बच्चे या बुज़ुर्ग हैं",
    rising: "पानी बढ़ रहा है",
    photos: "तस्वीरें",
    save: "रिपोर्ट सहेजें",
    savedNote: "इस फ़ोन में सहेज लिया गया। सिग्नल मिलते ही अपने आप भेज देगा।",
    queueTitle: "भेजना बाकी",
    queueEmpty: "कुछ बाकी नहीं। सब नियंत्रण कक्ष तक पहुँच गया।",
    nothingWaiting: "कुछ बाकी नहीं",
    summary: (r, p) => `${r} रिपोर्ट · ${p} तस्वीरें`,
    justNow: "अभी",
    minAgo: n => `${n} मिनट पहले`,
    textReady: n => `लेख तैयार · ${n} तस्वीरें`,
    demoControls: "डेमो नियंत्रण",
    goOffline: "कनेक्शन बंद करना",
    goOnline: "कनेक्शन वापस लाना",
    forceSync: "अभी भेजें",
    unverified: "इस अनुवाद की जाँच अभी किसी मूल वक्ता ने नहीं की है।",
  },
};

const KEY = "floodaid_lang";

export function currentLang() {
  const saved = localStorage.getItem(KEY);
  if (saved && STRINGS[saved]) return saved;
  // Fall back to the phone's own language if we support it.
  const nav = (navigator.language || "en").slice(0, 2);
  return STRINGS[nav] ? nav : "en";
}

export function setLang(code) {
  if (STRINGS[code]) localStorage.setItem(KEY, code);
}

export function t(code) {
  // Missing key in a translation falls back to English rather than showing
  // a blank label. A blank button in a disaster app is a failure.
  return new Proxy(STRINGS[code] || STRINGS.en, {
    get: (obj, key) => (key in obj ? obj[key] : STRINGS.en[key]),
  });
}
