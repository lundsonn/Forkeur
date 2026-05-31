export default function Loading() {
  return (
    <div className="max-w-md mx-auto px-5">
      {/* Nav */}
      <div className="flex items-center justify-between pt-5 pb-4">
        <div className="w-20 h-5 bg-stone-100 rounded animate-pulse" />
        <div className="w-16 h-4 bg-stone-100 rounded animate-pulse" />
      </div>

      {/* Hero */}
      <div className="mb-4">
        <div className="w-56 h-8 bg-stone-100 rounded animate-pulse mb-2" />
        <div className="w-40 h-8 bg-stone-100 rounded animate-pulse" />
      </div>

      {/* Search */}
      <div className="border border-stone-200 rounded-xl px-4 py-3 mb-5">
        <div className="w-40 h-4 bg-stone-100 rounded animate-pulse" />
      </div>

      {/* Cuisine chips */}
      <div className="flex gap-2 mb-4">
        {[60, 72, 54, 80].map((w, i) => (
          <div key={i} className="h-7 bg-stone-100 rounded-full animate-pulse" style={{ width: w }} />
        ))}
      </div>

      {/* Label */}
      <div className="w-24 h-2.5 bg-stone-100 rounded animate-pulse mb-3" />

      {/* 6 card skeletons */}
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="py-4 border-b border-stone-100 last:border-0">
          <div className="flex items-start justify-between mb-3">
            <div>
              <div className="w-36 h-4 bg-stone-100 rounded animate-pulse mb-1.5" />
              <div className="w-24 h-3 bg-stone-100 rounded animate-pulse" />
            </div>
            <div className="w-3 h-3 bg-stone-100 rounded animate-pulse mt-0.5" />
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            {[0, 1, 2].map((j) => (
              <div key={j} className="h-12 bg-stone-100 rounded-lg animate-pulse" />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
