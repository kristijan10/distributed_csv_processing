import { useCallback, useEffect, useRef, useState } from "react";
import UploadForm from "./components/UploadForm";
import JobList from "./components/JobList";
import JobDurationChart from "./components/JobDurationChart";
import PipelineOverview from "./components/PipelineOverview";
import MetricsPanel from "./components/MetricsPanel";
import { createJob, runJob, listJobs } from "./api";

const POLL_INTERVAL_MS = 3000;
const ACTIVE_STATUSES = new Set(["Pending", "Running"]);
const TABS = [
  { id: "jobs", label: "Jobs" },
  { id: "metrics", label: "Metrics" },
];

function App() {
  const [jobs, setJobs] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [listError, setListError] = useState(null);
  const [activeTab, setActiveTab] = useState("jobs");
  const jobsRef = useRef(jobs);
  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  const refresh = useCallback(async () => {
    try {
      const data = await listJobs();
      setJobs(data);
      setListError(null);
    } catch (err) {
      setListError(err.message);
    }
  }, []);

  useEffect(() => {
    refresh();

    // Skip the network round-trip while the tab is hidden, or once every
    // job is in a terminal state - there's nothing left that could change.
    // A tab becoming visible again catches up immediately rather than
    // waiting out the rest of the interval.
    const interval = setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (!jobsRef.current.some((job) => ACTIVE_STATUSES.has(job.status)))
        return;
      refresh();
    }, POLL_INTERVAL_MS);

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refresh]);

  async function handleSubmit(file, workerCount) {
    setSubmitting(true);
    try {
      const job = await createJob(file, workerCount);
      await runJob(job.id);
      await refresh();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="app mx-auto max-w-4xl px-6 py-12 sm:py-16">
      <header className="mb-10">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl dark:text-white">
          Distributed Batch Processing Platform
        </h1>
        <p className="mt-2 max-w-xl text-slate-500 dark:text-slate-400">
          Upload a CSV, choose how many worker pods to split it across, and
          watch it run on the local Kubernetes cluster.
        </p>
      </header>

      <nav className="mb-8 flex gap-2 border-b border-slate-200 dark:border-slate-800">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              activeTab === tab.id
                ? "border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400"
                : "border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === "jobs" && (
        <>
          {/* <PipelineOverview /> */}

          <div className="mt-8">
            <UploadForm onSubmit={handleSubmit} submitting={submitting} />
          </div>

          <section className="jobs-section mt-12">
            <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-white">
              Jobs
            </h2>
            {listError && (
              <p className="error-text mb-4 text-sm text-red-600 dark:text-red-400">
                Could not load jobs: {listError}
              </p>
            )}
            <JobList jobs={jobs} />
          </section>

          <section className="job-duration-section mt-12">
            <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-white">
              Job duration by worker count
            </h2>
            <JobDurationChart jobs={jobs} />
          </section>
        </>
      )}

      {activeTab === "metrics" && (
        <section className="metrics-section">
          <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-white">
            Benchmark metrics
          </h2>
          <MetricsPanel />
        </section>
      )}
    </main>
  );
}

export default App;
