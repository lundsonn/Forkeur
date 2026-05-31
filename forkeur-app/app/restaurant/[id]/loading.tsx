export default function Loading() {
  return (
    <div className="max-w-md mx-auto">
      {/* Nav */}
      <div className="flex items-center px-5 pt-5 pb-3">
        <div className="w-4 h-4 bg-stone-100 rounded animate-pulse mr-auto" />
        <div className="w-16 h-4 bg-stone-100 rounded animate-pulse" />
      </div>

      {/* Restaurant header */}
      <div className="px-5 pb-4 mt-2">
        <div className="w-44 h-7 bg-stone-100 rounded animate-pulse mb-2" />
        <div className="w-36 h-4 bg-stone-100 rounded animate-pulse" />
      </div>

      <div className="px-5">
        {/* "BEST RIGHT NOW" label */}
        <div className="w-24 h-2.5 bg-stone-100 rounded animate-pulse mb-3" />

        {/* Platform name */}
        <div className="w-40 h-8 bg-stone-100 rounded animate-pulse mb-1" />
        <div className="w-48 h-4 bg-stone-100 rounded animate-pulse mb-5" />

        {/* Metrics row */}
        <div className="flex gap-6 mb-5">
          {[0, 1, 2].map((i) => (
            <div key={i}>
              <div className="w-14 h-6 bg-stone-100 rounded animate-pulse mb-1" />
              <div className="w-10 h-2.5 bg-stone-100 rounded animate-pulse" />
            </div>
          ))}
        </div>

        {/* Compare rows */}
        <div className="border-t border-stone-100 pt-4">
          <div className="w-28 h-4 bg-stone-100 rounded animate-pulse mb-4" />
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="flex items-center justify-between py-3 border-b border-stone-100"
            >
              <div className="w-24 h-4 bg-stone-100 rounded animate-pulse" />
              <div className="w-12 h-4 bg-stone-100 rounded animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
