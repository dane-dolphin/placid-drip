// Copyright (c) 2026, Placid and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Batch Lesson Access", {
// 	refresh(frm) {

// 	},
// });

frappe.ui.form.on('Batch Lesson Access', {
  setup(frm) {
    // evaluator can only pick batches they evaluate (admin can see all)
    frm.set_query('batch', () => ({
      query: 'placid_drip.api.batch_lesson_access.get_evaluator_batches',
    }));

    // course list should depend on batch
    frm.set_query('course', () => ({
      query: 'placid_drip.api.batch_lesson_access.get_evaluator_courses',
      filters: { batch: frm.doc.batch },
    }));

    // lesson list should depend on course
    frm.set_query('lesson', () => ({
      filters: { course: frm.doc.course },
    }));
  },

  batch(frm) {
    frm.set_value('course', null);
    frm.set_value('lesson', null);
  },

  course(frm) {
    frm.set_value('lesson', null);
  },
});