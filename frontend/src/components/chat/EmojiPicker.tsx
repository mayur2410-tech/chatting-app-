import { useState } from "react";

const CATEGORIES: Array<{ label: string; icon: string; emojis: string }> = [
  {
    label: "Smileys",
    icon: "😀",
    emojis:
      "😀 😃 😄 😁 😆 😅 😂 🤣 🙂 🙃 😉 😊 😇 🥰 😍 🤩 😘 😗 😚 😙 😋 😛 😜 🤪 😝 🤗 🤭 🤫 🤔 🤐 🤨 😐 😑 😶 😏 😒 🙄 😬 😌 😔 😪 😴 😷 🥵 🥶 🥴 😵 🤯 🥳 😎 🤓 😕 😟 🙁 😮 😯 😲 😳 🥺 😦 😧 😨 😰 😥 😢 😭 😱 😖 😣 😞 😓 😩 😫 🥱 😤 😡 😠",
  },
  {
    label: "Gestures",
    icon: "👍",
    emojis:
      "👋 🤚 ✋ 🖖 👌 🤌 🤏 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👍 👎 ✊ 👊 🤛 🤜 👏 🙌 👐 🤲 🤝 🙏 💪 🫶 👀 🙈 🙉 🙊",
  },
  {
    label: "Hearts",
    icon: "❤️",
    emojis: "❤️ 🧡 💛 💚 💙 💜 🤎 🖤 🤍 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💟 💋 💌 ✨ 🌹 💐",
  },
  {
    label: "Food",
    icon: "☕",
    emojis:
      "☕ 🍵 🧋 🍷 🍸 🍹 🍺 🥂 🍕 🍔 🍟 🌮 🌯 🍣 🍜 🍝 🥗 🍰 🎂 🧁 🍩 🍪 🍫 🍿 🍎 🍓 🍒 🍑 🍉 🍌 🥑",
  },
  {
    label: "Activities",
    icon: "🎉",
    emojis:
      "✈️ 🛫 🛬 🛩️ 🚁 🌍 🧳 🗺️ 🎉 🎊 🎈 🎁 🎶 🎵 🎧 🎮 🎲 🎬 📚 🚗 🏖️ ⛰️ 🏠 🌙 ⭐ ☀️ 🌧️ ⛄ 🌈 🔥 💯 ✅ ❌ ❓ ❗ 💤 ⏰ 📍",
  },
];

interface EmojiPickerProps {
  onSelect: (emoji: string) => void;
}

export function EmojiPicker({ onSelect }: EmojiPickerProps) {
  const [active, setActive] = useState(0);
  const emojis = CATEGORIES[active].emojis.split(" ");

  return (
    <div className="animate-fade-up border-t border-sky-900/10 bg-white dark:border-white/10 dark:bg-slate-900">
      <div className="no-scrollbar flex gap-1 overflow-x-auto px-2 pt-2" role="tablist" aria-label="Emoji categories">
        {CATEGORIES.map((c, i) => (
          <button
            key={c.label}
            type="button"
            role="tab"
            aria-selected={i === active}
            aria-label={c.label}
            onClick={() => setActive(i)}
            className={`flex h-9 min-w-11 items-center justify-center rounded-lg text-xl transition ${
              i === active ? "bg-sky-100 dark:bg-slate-800" : "opacity-60 hover:opacity-100"
            }`}
          >
            {c.icon}
          </button>
        ))}
      </div>
      <div className="grid h-52 grid-cols-8 content-start gap-0.5 overflow-y-auto p-2 sm:grid-cols-10" role="tabpanel">
        {emojis.map((e) => (
          <button
            key={e}
            type="button"
            onClick={() => onSelect(e)}
            className="flex aspect-square items-center justify-center rounded-lg text-2xl transition hover:bg-sky-100 active:scale-90 dark:hover:bg-slate-800"
            aria-label={`Insert ${e}`}
          >
            {e}
          </button>
        ))}
      </div>
    </div>
  );
}
