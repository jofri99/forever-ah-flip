import { useState } from "react"

import { Assume } from "@/components/bits"
import { Input } from "@/components/ui/input"
import { useApp } from "@/lib/app"

/** Das verfuegbare Gold. Der Text bleibt, wie er getippt wurde; gerechnet wird mit der Zahl darin. */
export function GoldField() {
  const { a, setA } = useApp()
  const [text, setText] = useState(String(a.gold))
  return (
    <Assume label="My gold" after="g">
      <Input
        value={text}
        inputMode="numeric"
        aria-label="My gold"
        className="h-8 w-24 text-right"
        onChange={(event) => {
          setText(event.target.value)
          setA({ gold: Math.max(0, parseInt(event.target.value.replace(/\D/g, ""), 10) || 0) })
        }}
      />
    </Assume>
  )
}
