"use client"

import { useRouter } from "next/navigation"

import { RouteBuilder } from "@/features/automations/route-builder"

export default function Page() {
  const router = useRouter()
  return <RouteBuilder onCreated={(routeId) => router.push(`/automations/telegram/${routeId}`)} />
}
