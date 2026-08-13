"use client"

import { useQuery } from "@tanstack/react-query"
import { createContext, useContext, useMemo } from "react"

import { getDateTimeSettings } from "@/features/settings/date-time-api"
import { DEFAULT_TIME_ZONE } from "@/lib/date-time"
import { queryKeys } from "@/lib/query-keys"

type DateTimeContextValue = {
  timezone: string
}

const DateTimeContext = createContext<DateTimeContextValue>({
  timezone: DEFAULT_TIME_ZONE,
})

export function DateTimeProvider({ children }: { children: React.ReactNode }) {
  const query = useQuery({
    queryKey: queryKeys.dateTimeSettings,
    queryFn: getDateTimeSettings,
  })
  const value = useMemo(
    () => ({
      timezone: query.data?.timezone ?? DEFAULT_TIME_ZONE,
    }),
    [query.data],
  )

  return <DateTimeContext.Provider value={value}>{children}</DateTimeContext.Provider>
}

export function useDateTime() {
  return useContext(DateTimeContext)
}
