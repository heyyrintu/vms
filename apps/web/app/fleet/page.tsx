"use client";

import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import type { Driver, Paginated, Vehicle, Vendor } from "@/lib/types";
import { Empty, ErrorNotice, Loading, PageHeader, StatusBadge } from "@/components/UI";
import { DriverDocuments } from "@/components/DriverDocuments";

async function uploadDriverDocument(file: File, kind: string, driverId: number) {
  const body = new FormData();
  body.append("file", file);
  body.append("kind", kind);
  body.append("object_type", "driver");
  body.append("object_id", String(driverId));
  return api("/documents/", { method: "POST", body });
}

export default function FleetPage() {
  const data = useQuery({
    queryKey: ["fleet"],
    queryFn: async () => ({
      vendors: listResults(await api<Paginated<Vendor>>("/vendors/?page_size=200")),
      vehicles: listResults(await api<Paginated<Vehicle>>("/vehicles/?page_size=200")),
      drivers: listResults(await api<Paginated<Driver>>("/drivers/?page_size=200")),
    }),
  });
  const [vehicle, setVehicle] = useState({
    registration_no: "",
    vendor: "",
    vehicle_type: "32 FT MXL",
    capacity: "",
    active: true,
  });
  const [driver, setDriver] = useState({ name: "", phone: "", vendor: "", active: true });
  const [editingVehicle, setEditingVehicle] = useState<number | null>(null);
  const [editingDriver, setEditingDriver] = useState<number | null>(null);
  const [aadhaar, setAadhaar] = useState<File | null>(null);
  const [pan, setPan] = useState<File | null>(null);
  const [licence, setLicence] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [fileKey, setFileKey] = useState(0);
  const [error, setError] = useState<unknown>();
  const addVehicle = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api(editingVehicle ? `/vehicles/${editingVehicle}/` : "/vehicles/", {
        method: editingVehicle ? "PATCH" : "POST",
        body: JSON.stringify({ ...vehicle, vendor: Number(vehicle.vendor), capacity: vehicle.capacity || null }),
      });
      setVehicle({ registration_no: "", vendor: "", vehicle_type: "32 FT MXL", capacity: "", active: true });
      setEditingVehicle(null);
      data.refetch();
    } catch (reason) {
      setError(reason);
    }
  };
  const addDriver = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const created = await api<Driver>(editingDriver ? `/drivers/${editingDriver}/` : "/drivers/", {
        method: editingDriver ? "PATCH" : "POST",
        body: JSON.stringify({ ...driver, vendor: Number(driver.vendor) }),
      });
      if (aadhaar) await uploadDriverDocument(aadhaar, "AADHAAR", created.id);
      if (pan) await uploadDriverDocument(pan, "PAN", created.id);
      if (licence) await uploadDriverDocument(licence, "DRIVING_LICENSE", created.id);
      setDriver({ name: "", phone: "", vendor: "", active: true });
      setEditingDriver(null);
      setAadhaar(null);
      setPan(null);
      setLicence(null);
      setFileKey((value) => value + 1);
      await data.refetch();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };
  const toggleActive = async (kind: "vehicles" | "drivers", id: number, active: boolean) => {
    try {
      await api(`/${kind}/${id}/`, { method: "PATCH", body: JSON.stringify({ active: !active }) });
      await data.refetch();
    } catch (reason) {
      setError(reason);
    }
  };
  if (data.isPending) return <Loading />;
  if (data.error) return <ErrorNotice error={data.error} />;
  return (
    <>
      <PageHeader
        title="Fleet & drivers"
        description="Vehicle master and vendor-linked drivers with protected identity verification."
      />
      {Boolean(error) && <ErrorNotice error={error} />}
      <div className="split">
        <form className="panel" onSubmit={addVehicle}>
          <div className="panel-head">
            <h2>{editingVehicle ? "Edit vehicle" : "Add vehicle"}</h2>
          </div>
          <div className="panel-body form-grid two">
            <div className="field">
              <label>Registration no.</label>
              <input
                className="input"
                required
                value={vehicle.registration_no}
                onChange={(e) => setVehicle({ ...vehicle, registration_no: e.target.value })}
              />
            </div>
            <div className="field">
              <label>Transporter</label>
              <select
                className="input"
                required
                value={vehicle.vendor}
                onChange={(e) => setVehicle({ ...vehicle, vendor: e.target.value })}
              >
                <option value="">Select</option>
                {data.data!.vendors.map((v) => (
                  <option value={v.id} key={v.id}>
                    {v.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Vehicle type</label>
              <input
                className="input"
                required
                value={vehicle.vehicle_type}
                onChange={(e) => setVehicle({ ...vehicle, vehicle_type: e.target.value })}
              />
            </div>
            <div className="field">
              <label>Capacity</label>
              <input
                type="number"
                className="input"
                value={vehicle.capacity}
                onChange={(e) => setVehicle({ ...vehicle, capacity: e.target.value })}
              />
            </div>
          </div>
          <div className="panel-body actions" style={{ paddingTop: 0 }}>
            {editingVehicle && (
              <button
                type="button"
                className="button"
                onClick={() => {
                  setEditingVehicle(null);
                  setVehicle({
                    registration_no: "",
                    vendor: "",
                    vehicle_type: "32 FT MXL",
                    capacity: "",
                    active: true,
                  });
                }}
              >
                Cancel
              </button>
            )}
            <button className="button primary">{editingVehicle ? "Save vehicle" : "Create vehicle"}</button>
          </div>
        </form>
        <form className="panel" onSubmit={addDriver}>
          <div className="panel-head">
            <h2>{editingDriver ? "Edit driver" : "Add driver"}</h2>
          </div>
          <div className="panel-body form-grid two">
            <div className="field">
              <label>Name</label>
              <input
                className="input"
                required
                value={driver.name}
                onChange={(e) => setDriver({ ...driver, name: e.target.value })}
              />
            </div>
            <div className="field">
              <label>Transporter</label>
              <select
                className="input"
                required
                value={driver.vendor}
                onChange={(e) => setDriver({ ...driver, vendor: e.target.value })}
              >
                <option value="">Select</option>
                {data.data!.vendors.map((v) => (
                  <option value={v.id} key={v.id}>
                    {v.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field span-2">
              <label>Phone (protected)</label>
              <input
                className="input"
                required
                value={driver.phone}
                onChange={(e) => setDriver({ ...driver, phone: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="driver-aadhaar">Aadhaar document</label>
              <input
                id="driver-aadhaar"
                key={`aadhaar-${fileKey}`}
                type="file"
                className="input"
                accept=".pdf,image/jpeg,image/png"
                onChange={(e) => setAadhaar(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="field">
              <label htmlFor="driver-pan">PAN document</label>
              <input
                id="driver-pan"
                key={`pan-${fileKey}`}
                type="file"
                className="input"
                accept=".pdf,image/jpeg,image/png"
                onChange={(e) => setPan(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="field span-2">
              <label htmlFor="driver-licence">Driving licence</label>
              <input
                id="driver-licence"
                key={`licence-${fileKey}`}
                type="file"
                className="input"
                accept=".pdf,image/jpeg,image/png"
                onChange={(e) => setLicence(e.target.files?.[0] ?? null)}
              />
            </div>
          </div>
          <div className="panel-body actions" style={{ paddingTop: 0 }}>
            {editingDriver && (
              <button
                type="button"
                className="button"
                onClick={() => {
                  setEditingDriver(null);
                  setDriver({ name: "", phone: "", vendor: "", active: true });
                }}
              >
                Cancel
              </button>
            )}
            <button disabled={busy} className="button primary">
              {busy ? "Saving…" : editingDriver ? "Save driver" : "Create driver"}
            </button>
          </div>
        </form>
      </div>
      <section className="panel">
        <div className="panel-head">
          <h2>Vehicle master</h2>
        </div>
        {data.data!.vehicles.length === 0 ? (
          <Empty />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Registration</th>
                  <th>Transporter</th>
                  <th>Type</th>
                  <th>Capacity</th>
                  <th>Status / action</th>
                </tr>
              </thead>
              <tbody>
                {data.data!.vehicles.map((v) => (
                  <tr key={v.id}>
                    <td>
                      <strong>{v.registration_no}</strong>
                    </td>
                    <td>{v.vendor_name}</td>
                    <td>{v.vehicle_type}</td>
                    <td>{v.capacity || "—"}</td>
                    <td>
                      <StatusBadge value={v.active ? "ACTIVE" : "INACTIVE"} />
                      <div className="actions">
                        <button
                          className="button small"
                          onClick={() => {
                            setEditingVehicle(v.id);
                            setVehicle({
                              registration_no: v.registration_no,
                              vendor: String(v.vendor),
                              vehicle_type: v.vehicle_type,
                              capacity: v.capacity || "",
                              active: v.active,
                            });
                            window.scrollTo({ top: 0, behavior: "smooth" });
                          }}
                        >
                          Edit
                        </button>
                        <button className="button small" onClick={() => toggleActive("vehicles", v.id, v.active)}>
                          {v.active ? "Deactivate" : "Activate"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Driver master</h2>
        </div>
        {data.data!.drivers.length === 0 ? (
          <Empty />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Transporter</th>
                  <th>Protected phone</th>
                  <th>KYC documents</th>
                  <th>Status / action</th>
                </tr>
              </thead>
              <tbody>
                {data.data!.drivers.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <strong>{d.name}</strong>
                    </td>
                    <td>{d.vendor_name}</td>
                    <td>{d.phone}</td>
                    <td>
                      <DriverDocuments driverId={d.id} />
                    </td>
                    <td>
                      <StatusBadge value={d.active ? "ACTIVE" : "INACTIVE"} />
                      <div className="actions">
                        <button
                          className="button small"
                          onClick={() => {
                            setEditingDriver(d.id);
                            setDriver({ name: d.name, phone: d.phone, vendor: String(d.vendor), active: d.active });
                            window.scrollTo({ top: 0, behavior: "smooth" });
                          }}
                        >
                          Edit
                        </button>
                        <button className="button small" onClick={() => toggleActive("drivers", d.id, d.active)}>
                          {d.active ? "Deactivate" : "Activate"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
