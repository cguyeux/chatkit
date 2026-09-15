"use client"

import { ColorScheme } from "@openai/chatkit-react"
import ChatKitComponent from "./ChatKitComponent"
import { useState, useEffect } from "react"

const USERID_STORAGE_KEY = "userId"
const THEME_STORAGE_KEY = "chatkit-theme"

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch (error) {
    console.error("Failed to persist", key, error)
  }
}

export default function Home() {
  // A free-form string that identifies the end user across visits (same
  // learner state server-side as long as the browser keeps it).
  const [userId, setUserId] = useState<string | null>(null)
  const [theme, setTheme] = useState<ColorScheme>("light")

  useEffect(() => {
    const existing = readStorage(USERID_STORAGE_KEY)
    if (existing === null) {
      const id = crypto.randomUUID()
      setUserId(id)
      writeStorage(USERID_STORAGE_KEY, id)
    } else {
      setUserId(existing)
    }
    const storedTheme = readStorage(THEME_STORAGE_KEY)
    if (storedTheme === "dark" || storedTheme === "light") {
      setTheme(storedTheme)
    }
  }, [])

  const toggleTheme = () => {
    setTheme((v) => {
      const next: ColorScheme = v === "dark" ? "light" : "dark"
      writeStorage(THEME_STORAGE_KEY, next)
      return next
    })
  }

  return (
    <main
      className={`flex min-h-screen flex-col items-center bg-slate-100 dark:bg-slate-950 ${
        theme === "dark" ? "dark" : ""
      }`}
    >
      <div className="mx-auto flex h-[100dvh] w-full max-w-4xl flex-col px-2 py-2 sm:px-4">
        <div className="flex w-full flex-row flex-wrap items-center justify-end gap-2 pb-2">
          <button
            type="button"
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
            onClick={toggleTheme}
          >
            {theme === "dark" ? "Mode clair" : "Mode sombre"}
          </button>
        </div>
        {userId === null ? null : <ChatKitComponent userId={userId} theme={theme} />}
      </div>
    </main>
  )
}
