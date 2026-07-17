import Form from "@rjsf/core";
import type { IChangeEvent } from "@rjsf/core";
import type { RJSFSchema } from "@rjsf/utils";
import validator from "@rjsf/validator-ajv8";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api";
import { useApi } from "../apiContext";
import { useAsync } from "../hooks";
import type { Item, JsonSchema } from "../types";
import { Breadcrumb, ErrorBox, Loading } from "./ui";

/** Drop the `$schema` meta reference (draft 2020-12) so RJSF's AJV8 (draft-07)
 * validates the field subset our schemas use without meta-schema resolution. */
function forForm(schema: JsonSchema): RJSFSchema {
  const copy = { ...schema };
  delete copy.$schema;
  return copy as RJSFSchema;
}

export function ItemForm({ mode }: { mode: "create" | "edit" }) {
  const api = useApi();
  const navigate = useNavigate();
  const { name, id } = useParams() as { name: string; id?: string };

  const { data, error, loading } = useAsync(
    () =>
      Promise.all([
        api.getSchema(name),
        mode === "edit" && id ? api.getItem(name, id) : Promise.resolve(null),
      ]),
    [name, id, mode],
  );

  const [submitError, setSubmitError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!api.canWrite) {
    return <p className="notice">This is a read-only deployment; editing is disabled.</p>;
  }
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const [schema, existing]: [JsonSchema, Item | null] = data;

  async function onSubmit(e: IChangeEvent) {
    setSubmitting(true);
    setSubmitError(null);
    const formData = e.formData as Record<string, unknown>;
    try {
      if (mode === "create") {
        const item = await api.createItem(name, formData);
        navigate(`/c/${encodeURIComponent(name)}/${encodeURIComponent(item.id)}`);
      } else {
        await api.updateItem(name, id!, formData);
        navigate(`/c/${encodeURIComponent(name)}/${encodeURIComponent(id!)}`);
      }
    } catch (err) {
      setSubmitError(err as Error);
      setSubmitting(false);
    }
  }

  const heading = mode === "create" ? "New item" : `Edit ${id}`;

  return (
    <>
      <Breadcrumb
        parts={[
          { label: "Collections", to: "/" },
          { label: name, to: `/c/${encodeURIComponent(name)}` },
          { label: heading },
        ]}
      />
      <h1>{heading}</h1>

      {submitError && (
        <div className="notice">
          <div>{submitError.message}</div>
          {submitError instanceof ApiError && submitError.details && (
            <ul>
              {submitError.details.map((d, i) => (
                <li key={i} className="error-detail">
                  {d}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Form
        schema={forForm(schema)}
        validator={validator}
        formData={existing?.data}
        disabled={submitting}
        onSubmit={onSubmit}
      >
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? "Saving…" : mode === "create" ? "Create" : "Save"}
          </button>
        </div>
      </Form>
    </>
  );
}
