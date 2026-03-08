import { useEffect, useState } from "react";

type ApiStatus = {
  status: string;
};

type DbStatus = {
  status: string;
  database: string;
};

function App() {
  const [apiStatus, setApiStatus] = useState<string>("loading...");
  const [dbStatus, setDbStatus] = useState<string>("loading...");

  useEffect(() => {
    const fetchStatuses = async () => {
      try {
        const apiResponse = await fetch("http://127.0.0.1:8000/health");
        const apiData: ApiStatus = await apiResponse.json();
        setApiStatus(apiData.status);
      } catch {
        setApiStatus("error");
      }

      try {
        const dbResponse = await fetch("http://127.0.0.1:8000/health/db");
        const dbData: DbStatus = await dbResponse.json();
        setDbStatus(dbData.database);
      } catch {
        setDbStatus("error");
      }
    };

    fetchStatuses();
  }, []);

  return (
    <div style={{ padding: "24px", fontFamily: "Arial, sans-serif" }}>
      <h1>Chaos Twin</h1>
      <p>Codebase intelligence and failure simulation platform.</p>

      <div style={{ marginTop: "24px" }}>
        <h2>System Status</h2>
        <ul>
          <li>Frontend: running</li>
          <li>Backend API: {apiStatus}</li>
          <li>Database: {dbStatus}</li>
        </ul>
      </div>
    </div>
  );
}

export default App;