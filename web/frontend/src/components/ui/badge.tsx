import { type HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

// Ported from EDM's frontend/src/components/ui/badge.tsx (WeatherStar.tsx's
// UI depends on it) -- not one of the 3 primitives the plan named
// explicitly, but Badge isn't part of VOD & DVR Manager's brand template at
// all, so there's nothing to copy it FROM there. Restyled onto this app's
// token set: EDM's 'default' variant used a `text-primary-strong` token
// that doesn't exist in the VOD & DVR Manager token system copied into
// index.css -- swapped for plain `text-primary`, the closest equivalent.
interface BadgeProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'success' | 'destructive' | 'warning' | 'brand2' | 'brand3' | 'outline'
}

export function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
        {
          'bg-primary/20 text-primary': variant === 'default',
          'bg-success/15 text-success': variant === 'success',
          'bg-destructive/15 text-destructive': variant === 'destructive',
          'bg-warning/15 text-warning': variant === 'warning',
          'bg-brand2/20 text-brand2': variant === 'brand2',
          'bg-brand3/20 text-brand3': variant === 'brand3',
          'border border-border text-muted-foreground': variant === 'outline',
        },
        className,
      )}
      {...props}
    />
  )
}
