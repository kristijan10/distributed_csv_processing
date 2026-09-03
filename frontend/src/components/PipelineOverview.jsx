const STEPS = ['Upload CSV', 'Partition rows', 'Distribute to pods', 'Aggregate results', 'Download']

export default function PipelineOverview() {
  return (
    <ol className="flex items-start">
      {STEPS.map((label, i) => (
        <li key={label} className="flex flex-1 items-center last:flex-none">
          <div className="flex flex-col items-center text-center">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-sm font-medium text-white">
              {i + 1}
            </span>
            <span className="mt-2 max-w-24 text-xs text-slate-500 dark:text-slate-400">{label}</span>
          </div>
          {i < STEPS.length - 1 && <div className="mx-2 h-px flex-1 bg-slate-200 dark:bg-slate-800" />}
        </li>
      ))}
    </ol>
  )
}
