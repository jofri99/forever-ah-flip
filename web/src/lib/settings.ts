import { useCallback, useState } from "react"

const PREFIX = "fah:"

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    return raw == null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback // privates Fenster, gesperrter Speicher oder kaputter Eintrag
  }
}

function write<T>(key: string, value: T): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    // Ohne Speicher gilt die Einstellung eben nur fuer diese Sitzung.
  }
}

/**
 * Ein Zustand, der im Browser bleibt: Annahmen, Berufe, Merkliste, Einkaufsliste.
 * Faellt der Speicher aus, funktioniert alles weiter, nur ohne Gedaechtnis.
 */
export function usePersistent<T>(key: string, initial: T): [T, (next: T | ((current: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => read(key, initial))
  const update = useCallback(
    (next: T | ((current: T) => T)) => {
      setValue((current) => {
        const resolved = typeof next === "function" ? (next as (current: T) => T)(current) : next
        write(key, resolved)
        return resolved
      })
    },
    [key],
  )
  return [value, update]
}
